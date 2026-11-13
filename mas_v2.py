"""Hybrid MAS v2. Structured contracts, bounded orchestration and metadata-only audit."""
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from agents import FAQ, KnowledgeAgent, PredictionAgent, graph, read, words
from answering import answer_from_evidence, format_claims
from graph_store import load_graph
from large_model import CATEGORIES, FIELDS, LABS, RANGES, clean, encode

VERSION = "diaagent-v2.0"
ROOT = Path(__file__).resolve().parent
try:
    MODEL_VERSION = sha256((ROOT / "results/large_model.json").read_bytes()).hexdigest()[:12]
except OSError:
    MODEL_VERSION = "unavailable"
STOP = set("la gi cua co va de cho toi nao the khong o trong nhung cac mot khi do nhu sao lam".split())


@dataclass
class AgentMessage:
    request_id: str
    agent: str
    status: str
    payload: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    version: str = VERSION
    elapsed_ms: float = 0
    error: str | None = None


class Agent:
    input_contract = ""
    output_contract = ""

    def execute(self, request_id, **kwargs):
        started = time.perf_counter()
        try:
            payload, evidence = self.process(**kwargs)
            status = "degraded" if payload.get("degraded") else "ok"
            message = AgentMessage(request_id, type(self).__name__, status, payload, evidence)
        except ValueError as error:
            message = AgentMessage(request_id, type(self).__name__, "invalid", {"errors": [str(error)]})
        except Exception as error:
            message = AgentMessage(request_id, type(self).__name__, "error", error=type(error).__name__)
        message.elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        return message


def boolean(value):
    if isinstance(value, bool):
        return value
    if value in (None, "", "false", "0", 0):
        return False
    if value in ("on", "true", "1", 1):
        return True
    raise ValueError("Cờ lựa chọn phải là true/false.")


class PatientDataAgent(Agent):
    input_contract = "profile: object; question: string; optional height_cm/weight_kg/glucose_unit"
    output_contract = "features, model_name, warnings or validation errors"

    def process(self, profile):
        if not isinstance(profile, dict):
            raise ValueError("Hồ sơ cần là một object.")
        p = dict(profile)
        if not boolean(p.get("scope")):
            raise ValueError("Cần chọn hồ sơ giả định để chạy bản demo.")
        if not p.get("bmi") and p.get("weight_kg") and p.get("height_cm"):
            weight = float(str(p["weight_kg"]).replace(",", "."))
            height = float(str(p["height_cm"]).replace(",", "."))
            if not math.isfinite(weight + height) or not 20 <= height <= 250 or not 2 <= weight <= 400:
                raise ValueError("Kiểm tra cân nặng và chiều cao.")
            p["bmi"] = weight / (height / 100) ** 2
        unit = p.get("glucose_unit", "mg/dL")
        if unit not in ("mg/dL", "mmol/L"):
            raise ValueError("Đơn vị glucose phải là mg/dL hoặc mmol/L.")
        if unit == "mmol/L" and p.get("blood_glucose_level") not in (None, ""):
            p["blood_glucose_level"] = float(str(p["blood_glucose_level"]).replace(",", ".")) * 18.0182
        # Preserve finite out-of-training values for explicit review flags.
        for key, limits in RANGES.items():
            raw = p.get(key)
            if raw in (None, ""):
                continue
            value = float(str(raw).replace(",", "."))
            if not math.isfinite(value):
                raise ValueError(f"{key} phải là số hữu hạn.")
            if key not in ("hypertension", "heart_disease") and not 0 < value <= 1000:
                raise ValueError(f"{key} phải lớn hơn 0 và không quá 1000.")
        strict = dict(p)
        outside = []
        for key, (low, high) in RANGES.items():
            if p.get(key) not in (None, "") and key not in ("hypertension", "heart_disease"):
                value = float(str(p[key]).replace(",", "."))
                if not low <= value <= high:
                    outside.append(key)
                    strict[key] = min(high, max(low, value))
        features = clean(strict)
        for key in outside:
            features[key] = float(str(p[key]).replace(",", "."))
        name = "full" if all(k in features for k in LABS) else "screening"
        timing = p.get("glucose_timing", "unknown")
        if timing not in ("unknown", "fasting", "random"):
            raise ValueError("Thời điểm đo glucose không hợp lệ.")
        return dict(features=features, model_name=name, outside=outside,
                    glucose_timing=timing, warnings=["Ngoài miền train: " + ", ".join(outside)] if outside else []), []


class DLPredictionAgent(Agent):
    input_contract = "validated features, model_name, outside"
    output_contract = "score, label, threshold, model_version, gray_zone, optional effects"

    def __init__(self):
        try:
            self.models = {name: PredictionAgent(m) for name, m in read("results/large_model.json").items()}
        except (OSError, ValueError, TypeError):
            self.models = {}

    def process(self, data, explain=False):
        if data["outside"]:
            return dict(prediction=None, degraded=True, reason="outside_training_domain"), []
        model = self.models[data["model_name"]]
        values = data["features"]
        prediction = model.predict(encode(values, model.model["fields"]))
        prediction["model_version"] = MODEL_VERSION
        result = dict(prediction=prediction, model_name=data["model_name"],
                      gray_zone=abs(prediction["score"] - prediction["threshold"]) < .1)
        if explain:
            effects = []
            for key, baseline in model.model["reference"].items():
                alternative = dict(values, **{key: baseline})
                effects.append((key, prediction["score"] - model.predict(encode(alternative, model.model["fields"]))["score"]))
            result["effects"] = sorted(effects, key=lambda item: -abs(item[1]))[:5]
        return result, []


class RuleBasedAgent(Agent):
    input_contract = "validated data, prediction, optional safety kind"
    output_contract = "auditable flags, needs_review, explicit timing assumptions"

    def __init__(self):
        self.thresholds = read("data/thresholds_v2.json")

    def process(self, data=None, prediction=None, safety=None, enabled=True):
        flags = []
        def flag(id_, text, review=False, source=None):
            flags.append(dict(id=id_, text=text, needs_review=review, source=source,
                              review_status="Luật học thuật, chưa được chuyên gia y tế duyệt"))
        if safety:
            flag("R00" if safety == "urgent" else "R01", "Liên hệ cấp cứu tại nơi bạn ở hoặc đến khoa cấp cứu." if safety == "urgent"
                 else "Hãy trao đổi với nhân viên y tế phụ trách về việc dùng hoặc thay đổi thuốc.", True)
            return dict(flags=flags, needs_review=True), []
        if not enabled:
            return dict(flags=[], needs_review=False), []
        x = data["features"]
        hba1c = x.get("HbA1c_level")
        glucose = x.get("blood_glucose_level")
        high_lab = False
        if hba1c is not None and hba1c >= self.thresholds["hba1c_diabetes"]:
            high_lab = True
            flag("R02", "HbA1c đạt ngưỡng tham khảo từ 6,5%. Cần nhân viên y tế đánh giá và xác nhận.", True, "K22")
        elif hba1c is not None and hba1c >= self.thresholds["hba1c_prediabetes"]:
            flag("R03", "HbA1c thuộc khoảng tham khảo tiền đái tháo đường.", True, "K22")
        if glucose is not None:
            if data["glucose_timing"] == "unknown":
                flag("R04", "Chưa rõ thời điểm đo glucose. Cần bổ sung thông tin trước khi đối chiếu ngưỡng lúc đói.", True, "K23")
            limit = self.thresholds["glucose_fasting"] if data["glucose_timing"] == "fasting" else self.thresholds["glucose_random"]
            if data["glucose_timing"] != "unknown" and glucose >= limit:
                high_lab = True
                flag("R05", "Glucose đạt ngưỡng tham khảo ứng với thời điểm đo đã khai báo. Cần xác nhận chuyên môn.", True, "K23")
        if x["bmi"] >= 30:
            flag("R06", "BMI từ 30, bổ sung chủ đề cân nặng và vận động phù hợp.", source="K15")
        if x["hypertension"] or x["heart_disease"]:
            flag("R07", "Hồ sơ có tăng huyết áp hoặc bệnh tim. Cần xem xét cùng tiền sử sức khỏe.")
        if x["smoking_history"] == "current":
            flag("R08", "Có hút thuốc hiện tại. Có thể trao đổi về hỗ trợ cai thuốc.", source="K14")
        if prediction and prediction["label"] == 0 and high_lab:
            flag("R09", "Mô hình phân loại thấp nhưng xét nghiệm đạt ngưỡng tham khảo. Kết quả cần được xem lại.", True, "K22" if hba1c is not None and hba1c >= 6.5 else "K23")
        if prediction and abs(prediction["score"] - prediction["threshold"]) < .1:
            flag("R10", "Điểm gần ngưỡng phân loại của mô hình.", True)
        if data["model_name"] == "screening":
            flag("R11", "Đang dùng mô hình sàng lọc do thiếu ít nhất một xét nghiệm.", True)
        if data["outside"]:
            flag("R12", "Đầu vào ngoài miền huấn luyện. Dừng suy luận mô hình.", True)
        return dict(flags=flags, needs_review=any(f["needs_review"] for f in flags)), []


class KGRAGAgent(Agent):
    input_contract = "question, context ID, optional profile and focused evidence IDs"
    output_contract = "ranked source evidence, retrieval steps, backend"

    def __init__(self, docs, relations, backend):
        self.kb = KnowledgeAgent(docs, relations)
        self.backend = backend
        self.counts = [Counter(words(d["title"] + " " + d["keys"] + " " + d["text"])) for d in docs]
        self.average_length = sum(map(lambda c: sum(c.values()), self.counts)) / len(docs)

    def retrieve(self, question, mode="hybrid"):
        graph_hits = self.kb.retrieve(question, graph_enabled=mode != "lexical")
        tokens = set(words(question)) - STOP
        scored = []
        for doc, counts in zip(self.kb.docs, self.counts):
            score = 0.
            for token in tokens:
                frequency = sum(token in c for c in self.counts)
                tf = counts[token]
                if tf:
                    idf = math.log(1 + (len(self.counts) - frequency + .5) / (frequency + .5))
                    score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * sum(counts.values()) / self.average_length))
            if score:
                scored.append(dict(doc, bm25=score))
        scored.sort(key=lambda d: (-d["bm25"], d["id"]))
        if mode == "bm25":
            return [dict(d, score=d["bm25"]) for d in scored[:5]]
        if mode == "lexical":
            return graph_hits
        ranking = {}
        # RRF preserves complementary ranks without mixing unlike score scales.
        for candidates in (graph_hits, scored[:8]):
            for rank, hit in enumerate(candidates, 1):
                current = ranking.setdefault(hit["id"], dict(hit, rrf=0.))
                current["rrf"] += 1 / (60 + rank)
        hits = sorted(ranking.values(), key=lambda d: (-d["rrf"], d["id"]))[:5]
        for hit in hits:
            edge = self.kb.relations.get(hit["id"])
            if edge:
                hit["path"] = [edge["head"], edge["relation"], edge["tail"]]
            hit["score"] = hit["rrf"]
        # Require a meaningful lexical/alias match before serving general questions.
        if not graph_hits or graph_hits[0]["score"] < .26:
            return []
        return hits

    def process(self, question="", context="", data=None, focus=(), mode="hybrid"):
        if focus:
            hits = [d for d in self.kb.docs if d["id"] in focus]
        else:
            query = " ".join(words(question))
            followup = any(p in query for p in ("chi so do", "thuoc do", "benh do", "noi them", "xet nghiem do"))
            if followup and context in self.kb.relations:
                question = self.kb.relations[context]["aliases"][0] + " " + question
            if data:
                question += " HbA1c glucose thời điểm đo theo dõi"
            hits = self.retrieve(question, mode) if question else []
            source_id = {" ".join(words(q)): id_ for q, id_ in FAQ.items()}.get(query)
            if source_id:
                exact = next(d for d in self.kb.docs if d["id"] == source_id)
                hits = [exact] + [h for h in hits if h["id"] != source_id][:2]
        for hit in hits:
            edge=self.kb.relations.get(hit["id"])
            if edge and "path" not in hit:
                hit=dict(hit,path=[edge["head"],edge["relation"],edge["tail"]])
                hits=[hit if item["id"]==hit["id"] else item for item in hits]
        return dict(backend=self.backend, query=question,
                    steps=["Hiểu truy vấn", "Nhận diện bí danh", "Quan hệ đồ thị",
                           "Tìm kiếm BM25", "Hợp nhất RRF", "Gắn nguồn"],
                    degraded=self.backend != "Neo4j"), hits


class ExplanationAgent(Agent):
    input_contract = "prediction, rule flags, ranked evidence, question"
    output_contract = "grounded narrative and separate prediction/rules/limitations"

    def process(self, question, evidence, prediction=None, rules=None, allow_external=False):
        if not evidence:
            return dict(answer="Kho tri thức chưa tìm thấy bằng chứng đủ phù hợp.", mode="Thiếu bằng chứng",
                        degraded=True), []
        claims, mode = answer_from_evidence(question, evidence[:3], allow_external=allow_external)
        used = {id_ for claim in claims for id_ in claim["evidence_ids"]}
        return dict(answer=format_claims(claims), mode=mode), [d for d in evidence if d["id"] in used]


class MonitoringAgent:
    input_contract = "metadata-only agent trace"
    output_contract = "request audit record, aggregate metrics"

    def __init__(self, path=None):
        self.path = Path(path or os.getenv("DIAAGENT_AUDIT_PATH", ROOT / "runs/trace.jsonl"))
        self.lock = threading.RLock()
        self.records = deque(maxlen=500)
        self.write_errors = 0
        if self.path.exists():
            try:
                for line in self.path.read_text(encoding="utf8").splitlines()[-500:]:
                    self.records.append(json.loads(line))
            except (OSError, ValueError):
                self.write_errors += 1

    def record(self, request_id, status, messages, started, evidence_count):
        # No profile values, question text, prediction score or narrative are logged.
        record = dict(request_id=request_id, version=VERSION,
                      timestamp=datetime.now(timezone.utc).isoformat(), status=status,
                      elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                      evidence_count=evidence_count,
                      agents=[dict(agent=m.agent, status=m.status, elapsed_ms=m.elapsed_ms,
                                   version=m.version, error=m.error) for m in messages])
        with self.lock:
            self.records.append(record)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_name(self.path.name + ".tmp")
                temporary.write_text("".join(json.dumps(r) + "\n" for r in self.records), encoding="utf8")
                temporary.replace(self.path)
            except OSError:
                self.write_errors += 1
        return record

    def trace(self, request_id):
        with self.lock:
            return next((dict(r) for r in self.records if r["request_id"] == request_id), None)

    def metrics(self):
        with self.lock:
            rows = list(self.records)
            return dict(version=VERSION, requests=len(rows), retention=500,
                        statuses=dict(Counter(r["status"] for r in rows)),
                        average_ms=round(sum(r["elapsed_ms"] for r in rows) / max(1, len(rows)), 3),
                        audit_write_errors=self.write_errors,
                        audit_storage="Local ephemeral storage on Render; resets with redeploy")


class RLAgent:
    input_contract = "synthetic simulation seed and episodes"
    output_contract = "simulation-only policy reward comparison"

    def process(self, seed=42, episodes=3000):
        import random
        if isinstance(episodes, bool) or not isinstance(episodes, int) or not 100 <= episodes <= 10000:
            raise ValueError("episodes phải là số nguyên từ 100 đến 10000.")
        rng = random.Random(seed)
        q = [[0.] * 3 for _ in range(6)]
        rewards = [[.3, .6, .4], [.4, .3, .7], [.6, .4, .5],
                   [.5, .7, .4], [.8, .4, .5], [.6, .5, .8]]
        for _ in range(episodes):
            s = rng.randrange(6)
            a = rng.randrange(3) if rng.random() < .15 else max(range(3), key=q[s].__getitem__)
            reward = int(rng.random() < rewards[s][a])
            q[s][a] += .05 * (reward - q[s][a])
        actions = [max(range(3), key=row.__getitem__) for row in q]
        return dict(simulation_only=True, seed=seed, episodes=episodes,
                    actions=["Dinh dưỡng", "Vận động", "Theo dõi"], policy=actions,
                    learned_expected_reward=sum(rewards[s][a] for s, a in enumerate(actions)) / 6,
                    random_expected_reward=sum(map(sum, rewards)) / 18,
                    reward_definition="Bernoulli synthetic educational preference; gamma=0")


MONITOR = MonitoringAgent()


class CoordinatorV2:
    def __init__(self, *, use_neo4j=True, monitor=None):
        self.monitor = monitor or MONITOR
        try:
            docs, relations, self.backend = load_graph(use_neo4j=use_neo4j)
        except Exception:
            docs, relations, self.backend = graph(use_neo4j=False)
        self.data_agent = PatientDataAgent()
        self.dl = DLPredictionAgent()
        self.rules = RuleBasedAgent()
        self.knowledge = KGRAGAgent(docs, relations, self.backend)
        self.explanation = ExplanationAgent()
        self.rl = RLAgent()
        self.kb = self.knowledge.kb

    def assess(self, profile=None, question="", *, context="", allow_external=False,
               retrieval_mode="hybrid", rules_enabled=True):
        if not isinstance(question, str) or len(question) > 600:
            raise ValueError("Câu hỏi phải là chuỗi tối đa 600 ký tự.")
        if profile is not None and not isinstance(profile, dict):
            raise ValueError("Hồ sơ cần là object.")
        if not isinstance(context, str) or len(context)>20:
            raise ValueError("Mã ngữ cảnh không hợp lệ.")
        started = time.perf_counter()
        request_id = str(uuid4())
        messages = []
        result = dict(request_id=request_id, version=VERSION, prediction=None, model_name=None,
                      flags=[], evidence=[], answer="", answer_mode="Mẫu giải thích",
                      status="ok", trace=[], backend=self.backend, needs_review=False,
                      limitations=["Điểm phân loại dữ liệu lịch sử, cần đánh giá chuyên môn khi sử dụng.",
                                   "Luật học thuật chưa được chuyên gia y tế duyệt."])
        def invoke(agent, **kwargs):
            message = agent.execute(request_id, **kwargs)
            messages.append(message)
            return message

        def finish():
            if result["status"] in ("degraded", "needs_review"):
                result["needs_review"] = True
            result["trace"] = [m.agent for m in messages] + ["MonitoringAgent"]
            result["messages"] = [asdict(m) for m in messages]
            audit = self.monitor.record(request_id, result["status"], messages, started, len(result["evidence"]))
            result["audit"] = audit
            return result

        query = " ".join(words(question))
        urgent = boolean((profile or {}).get("urgent")) or any(p in query for p in
                 ("kho tho", "bat tinh", "hon me", "non lien tuc", "tho mui trai cay"))
        medication = any(p in query for p in ("tang lieu", "giam lieu", "lieu insulin", "ngung thuoc",
                                             "bao nhieu vien", "bao nhieu mg", "lieu dung"))
        if urgent or medication:
            rule = invoke(self.rules, safety="urgent" if urgent else "medication")
            result["flags"] = rule.payload["flags"]
            result["answer"] = rule.payload["flags"][0]["text"]
            result["status"] = "needs_review"
            result["needs_review"] = True
            if urgent:
                result["evidence"] = [d for d in self.kb.docs if d["id"] == "K01"]
            return finish()
        data = None
        if profile is not None:
            validation = invoke(self.data_agent, profile=profile)
            if validation.status != "ok":
                result.update(status="invalid", answer=" ".join(validation.payload.get("errors", ["Không thể kiểm tra hồ sơ."])))
                return finish()
            data = validation.payload
            prediction = invoke(self.dl, data=data, explain=boolean(profile.get("explain")))
            result["prediction"] = prediction.payload.get("prediction")
            result["model_name"] = data["model_name"]
            result["effects"] = prediction.payload.get("effects", [])
            if prediction.status != "ok":
                result["status"] = "degraded"
            rule = invoke(self.rules, data=data, prediction=result["prediction"], enabled=rules_enabled)
            result["flags"] = rule.payload.get("flags", [])
            result["needs_review"] = rule.payload.get("needs_review", True)
            if rule.status != "ok":
                result["status"] = "degraded"

        if not question.strip() and not data:
            result.update(status="invalid", answer="Cần nhập câu hỏi hoặc hồ sơ.")
            return finish()
        if not data and any(p in query for p in ("chi so do", "thuoc do", "noi them")) and context not in self.kb.relations:
            result.update(status="needs_review", answer="Bạn muốn hỏi thêm về chủ đề nào?", answer_mode="Cần làm rõ")
            return finish()
        knowledge = invoke(self.knowledge, question=question, context=context, data=data, mode=retrieval_mode)
        hits = list(knowledge.evidence)
        # Review rules can trigger a bounded second retrieval focused on thresholds.
        focus = {f["source"] for f in result["flags"] if f.get("source") in ("K22", "K23")}
        if focus:
            extra = invoke(self.knowledge, focus=focus)
            hits = extra.evidence + [h for h in hits if h["id"] not in focus]
        explanation = invoke(self.explanation, question=question or "Giải thích hồ sơ giả định",
                             evidence=hits, prediction=result["prediction"], rules=result["flags"],
                             allow_external=allow_external)
        result["answer"] = explanation.payload.get("answer", "Không thể tạo phản hồi. Cần thử lại.")
        result["answer_mode"] = explanation.payload.get("mode", "Lỗi giải thích")
        result["evidence"] = explanation.evidence
        if knowledge.status != "ok" or explanation.status != "ok":
            result["status"] = "degraded"
        if result["needs_review"] and result["status"] == "ok":
            result["status"] = "needs_review"
        return finish()

    def run(self, profile):
        result = self.assess(profile, profile.get("question", ""))
        result["rule"] = "R0" if any(f["id"] == "R00" for f in result["flags"]) else "R4"
        result["topic"] = "Báo cáo hỗ trợ quyết định"
        return result

    def ask_detail(self, question, *, allow_external=False, context=""):
        result = self.assess(question=question, context=context, allow_external=allow_external)
        mode = result["answer_mode"]
        if any(f["id"] in ("R00", "R01") for f in result["flags"]):
            mode = "Luật an toàn"
        elif " ".join(words(question)) in {" ".join(words(q)) for q in FAQ}:
            mode = "FAQ"
        return result["answer"], result["evidence"], mode

    def compare(self, profile, field, value):
        if field not in ("bmi", "blood_glucose_level"):
            raise ValueError("Chọn BMI hoặc glucose.")
        old, _ = self.data_agent.process(profile)
        new, _ = self.data_agent.process(dict(profile, **{field: value}))
        if old["outside"] or new["outside"] or (field in LABS and old["model_name"] == "screening"):
            raise ValueError("So sánh cần giá trị trong miền train và đủ xét nghiệm cho glucose.")
        return self.dl.process(old)[0]["prediction"], self.dl.process(new)[0]["prediction"]

    def contracts(self):
        agents = [self.data_agent, self.dl, self.rules, self.knowledge, self.explanation, self.monitor, self.rl]
        return [dict(agent="CoordinatorAgent",input="profile and/or question",output="structured report and request ID",version=VERSION)] + [
            dict(agent=type(a).__name__, input=a.input_contract, output=a.output_contract, version=VERSION) for a in agents]

