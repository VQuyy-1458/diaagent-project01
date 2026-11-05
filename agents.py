import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from answering import answer_from_evidence, format_claims

ROOT = Path(__file__).resolve().parent
FIELDS = "Pregnancies Glucose BloodPressure SkinThickness Insulin BMI DPF Age".split()
ZERO_MISSING = set(FIELDS[1:6])
TOPICS = ["Xét nghiệm", "Dinh dưỡng", "Vận động", "Theo dõi"]
QUERIES = ["xét nghiệm a1c ogtt", "dinh dưỡng đĩa ăn nước lọc",
           "vận động thể lực đi bộ", "theo dõi đường huyết triệu chứng"]
FAQ = {
    "HbA1c là gì?": "K02",
    "OGTT là gì?": "K03",
    "Đường huyết lúc đói là gì?": "K04",
    "Triệu chứng thường gặp là gì?": "K05",
    "Mô hình đĩa ăn là gì?": "K07",
    "Vận động liên quan thế nào đến phòng ngừa típ 2?": "K06",
}
BOUNDS = [(0,20),(1,250),(1,150),(1,110),(1,900),(1,80),(0,3),(21,100)]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def words(text):
    text = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    return re.findall(r"[a-z0-9]+", "".join(c for c in text if not unicodedata.combining(c)))


def graph():
    docs = read("data/kb.json")
    relations = read("data/relations.json")
    if not os.getenv("NEO4J_URI"):
        return docs, relations, "Đồ thị JSON"
    from neo4j import GraphDatabase
    with GraphDatabase.driver(os.environ["NEO4J_URI"],
                              auth=(os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"])
                              if os.getenv("NEO4J_PASSWORD") else None) as driver:
        options = {"database_": os.getenv("NEO4J_DATABASE", "neo4j")}
        driver.execute_query("""
            UNWIND $docs AS row
            MERGE (p:P1Passage {id: row.id})
            SET p.title=row.title, p.text=row.text, p.keys=row.keys
            MERGE (t:P1Topic {name: row.topic})
            MERGE (s:P1Source {url: row.url})
            SET s.name=row.source
            MERGE (p)-[:ABOUT]->(t)
            MERGE (p)-[:FROM_SOURCE]->(s)
            """, docs=docs, **options)
        driver.execute_query("""
            UNWIND $relations AS row
            MATCH (p:P1Passage {id: row.id})
            MERGE (head:P1Concept {name: row.head})
            MERGE (tail:P1Concept {name: row.tail})
            MERGE (head)-[r:KNOWLEDGE_LINK {evidence_id: row.id}]->(tail)
            SET r.kind=row.relation, r.aliases=row.aliases
            MERGE (tail)-[:SUPPORTED_BY]->(p)
            """, relations=relations, **options)
        records, _, _ = driver.execute_query("""
            MATCH (p:P1Passage)-[:ABOUT]->(t:P1Topic),
                  (p)-[:FROM_SOURCE]->(s:P1Source)
            RETURN p.id AS id, p.title AS title, p.text AS text, p.keys AS keys,
                   t.name AS topic, s.url AS url, s.name AS source ORDER BY id
            """, **options)
        edges, _, _ = driver.execute_query("""
            MATCH (head:P1Concept)-[r:KNOWLEDGE_LINK]->(tail:P1Concept)
                  -[:SUPPORTED_BY]->(p:P1Passage)
            WHERE r.evidence_id = p.id
            RETURN p.id AS id, head.name AS head, r.kind AS relation,
                   tail.name AS tail, r.aliases AS aliases ORDER BY id
            """, **options)
    return [dict(row) for row in records], [dict(row) for row in edges], "Neo4j"



class KnowledgeAgent:
    def __init__(self, docs, relations=()):
        self.docs = docs
        self.relations = {row["id"]: row for row in relations}
        counts = [Counter(words(d["title"]+" "+(d["keys"]+" ")*3+d["text"])) for d in docs]
        freq = Counter(term for c in counts for term in c)
        self.idf = {term: 1+math.log((1+len(docs))/(1+n)) for term,n in freq.items()}
        self.vectors = [self.vector(c) for c in counts]

    def vector(self, counts):
        weights = {t:(1+math.log(n))*self.idf[t] for t,n in counts.items() if t in self.idf}
        norm = math.sqrt(sum(v*v for v in weights.values())) or 1
        return {t:v/norm for t,v in weights.items()}

    def retrieve(self, question, topic=None, *, graph_enabled=True):
        normalized = " ".join(words(question))
        aliases = {"hba1c": "a1c", "duong huyet luc doi": "glucose nhin an",
                   "nghiem phap dung nap duong": "ogtt glucose",
                   "an uong lanh manh": "dinh duong dia an"}
        additions = [v for phrase,v in aliases.items() if phrase in normalized]
        q = self.vector(Counter(words(" ".join([question, *additions]))))
        matched = {row["id"] for row in self.relations.values()
                   if any(f" {alias} " in f" {normalized} " for alias in row["aliases"])} if graph_enabled else set()
        linked_heads = {self.relations[id_]["head"] for id_ in matched}
        hits = []
        for d,v in zip(self.docs,self.vectors):
            if topic and d["topic"] != topic:
                continue
            score = sum(w*v.get(t,0) for t,w in q.items())
            edge = self.relations.get(d["id"])
            if d["id"] in matched:
                score += .18
            elif edge and edge["head"] in linked_heads and score >= .12:
                score += .035
            if score >= .12:
                hit = dict(d, score=round(score, 4))
                if edge:
                    hit["path"] = [edge["head"], edge["relation"], edge["tail"]]
                hits.append(hit)
        hits.sort(key=lambda d: (-d["score"],d["id"]))
        return hits[:3]

    def respond(self, question, topic=None, *, allow_external=False):
        hits = self.retrieve(question, topic)
        if not hits:
            return "Kho tri thức chưa tìm thấy đoạn đủ phù hợp.", [], "Thiếu bằng chứng"
        claims, mode = answer_from_evidence(question, hits, allow_external=allow_external)
        cited = {cid for claim in claims for cid in claim["evidence_ids"]}
        return format_claims(claims), [d for d in hits if d["id"] in cited], mode

    def answer(self, question, topic=None):
        text, hits, _ = self.respond(question, topic)
        return text, hits


class SafetyAgent:
    @staticmethod
    def inspect(profile):
        if profile.get("urgent"):
            return "R0", []
        if not profile.get("scope"):
            return "R1", []
        values = []
        for key,(lo,hi) in zip(FIELDS,BOUNDS):
            raw = profile.get(key)
            value = None if raw in ("",None) else float(str(raw).replace(",", "."))
            if key in ZERO_MISSING and value == 0:
                value = None
            if value is not None and not lo <= value <= hi:
                raise ValueError(f"{key} nằm ngoài phạm vi demo.")
            if key in ("Age","Pregnancies") and value is not None and not value.is_integer():
                raise ValueError(f"{key} cần là số nguyên.")
            values.append(value)
        if any(values[i] is None for i in (1,5,7)):
            return "R2",values
        return ("R3" if values[1] >= 200 else "R4"),values


class PredictionAgent:
    def __init__(self, model):
        self.model = model

    def predict(self, values):
        m = self.model
        h = [((m["median"][i] if v is None else v)-m["mean"][i])/m["scale"][i]
             for i,v in enumerate(values)]
        for i,(weights,bias) in enumerate(zip(m["weights"],m["bias"])):
            h = [sum(v*w for v,w in zip(h,col))+b for col,b in zip(zip(*weights),bias)]
            if i < len(m["bias"])-1:
                h = [max(v,0) for v in h]
        slope, intercept = m.get("calibration", [1.0, 0.0])
        logit = slope * h[0] + intercept
        score = 1/(1+math.exp(-max(-60,min(60,logit))))
        return dict(score=score,label=int(score>=m["threshold"]),threshold=m["threshold"])

    def explain(self, values):
        """Exact Shapley attribution for the fixed training-median reference."""
        reference = self.model["median"]
        observed = [i for i,value in enumerate(values) if value is not None and value != reference[i]]
        count = len(observed)
        if count == 0:
            return self.predict(reference)["score"], []
        size = 1 << count
        scores = []
        for mask in range(size):
            sample = reference.copy()
            for j,i in enumerate(observed):
                if mask & (1 << j):
                    sample[i] = values[i]
            scores.append(self.predict(sample)["score"])
        weights = [1 / (count * math.comb(count - 1, k)) for k in range(count)]
        effects = []
        for j,i in enumerate(observed):
            bit = 1 << j
            effect = sum(weights[mask.bit_count()] * (scores[mask | bit] - scores[mask])
                         for mask in range(size) if not mask & bit)
            effects.append((FIELDS[i], effect))
        return scores[0], sorted(effects, key=lambda item: (-abs(item[1]), item[0]))


class PlannerAgent:
    def __init__(self, q):
        self.q = q

    def choose(self, label, bmi, active):
        state = 4*label + 2*int(bmi>=30) + int(not active)
        return state, max(range(4),key=self.q[state].__getitem__)


class Coordinator:
    def __init__(self):
        docs,relations,self.backend = graph()
        self.kb = KnowledgeAgent(docs, relations)
        self.pred = PredictionAgent(read("results/model.json"))
        self.plan = PlannerAgent(read("results/q.json"))

    def emergency(self):
        return ("Dấu hiệu đã chọn có thể cần xử trí khẩn cấp. Hãy liên hệ dịch vụ cấp cứu tại nơi bạn ở hoặc đến khoa cấp cứu ngay. [K01]",
                [d for d in self.kb.docs if d["id"]=="K01"])

    def ask(self, question):
        text, hits, _ = self.ask_detail(question)
        return text, hits

    def ask_detail(self, question, *, allow_external=False, context=""):
        query = " ".join(words(question))
        if any(p in query for p in ("kho tho","bat tinh","hon me","non lien tuc","ketone cao","tho mui trai cay")):
            text, hits = self.emergency()
            return text, hits, "Luật an toàn"
        if any(p in query for p in ("lieu insulin","tang lieu","giam lieu","ngung thuoc")):
            return "Hãy trao đổi với nhân viên y tế phụ trách điều trị về liều hoặc thay đổi thuốc.", [], "Luật an toàn"
        faq = {" ".join(words(prompt)): id_ for prompt,id_ in FAQ.items()}
        source_id = faq.get(query)
        if source_id:
            for item in self.kb.docs:
                if item["id"] == source_id:
                    return f'{item["text"]} [{source_id}]', [item], "FAQ"
        follow_up = any(phrase in query for phrase in ("xet nghiem do", "chi so do", "cach do", "noi them"))
        named_concept = any(f" {alias} " in f" {query} "
                            for edge in self.kb.relations.values() for alias in edge["aliases"])
        if follow_up and not named_concept:
            previous = self.kb.relations.get(context)
            if not previous:
                return "Bạn muốn hỏi thêm về xét nghiệm hoặc chủ đề nào?", [], "Cần làm rõ"
            question = f'{previous["tail"]}. {question}'
        return self.kb.respond(question, allow_external=allow_external)

    def compare(self, profile, field, new_value):
        base_rule, values = SafetyAgent.inspect(profile)
        if base_rule not in ("R3", "R4") or field not in ("Glucose", "BMI"):
            raise ValueError("Cần hồ sơ hợp lệ và trường Glucose hoặc BMI.")
        alternative = dict(profile, **{field: new_value})
        next_rule, next_values = SafetyAgent.inspect(alternative)
        if next_rule not in ("R3", "R4"):
            raise ValueError("Cần nhập giá trị giả định hợp lệ.")
        return self.pred.predict(values), self.pred.predict(next_values)

    def run(self, profile):
        rule,values = SafetyAgent.inspect(profile)
        result = dict(rule=rule,trace=["SafetyAgent"],prediction=None,topic=None,evidence=[],backend=self.backend)
        if rule=="R0":
            result["answer"],result["evidence"] = self.emergency()
        elif rule=="R1":
            result["answer"] = "Hồ sơ ngoài phạm vi trình diễn Pima. Có thể dùng mục hỏi đáp tri thức."
        elif rule=="R2":
            result["answer"] = "Cần glucose 2 giờ OGTT, BMI và tuổi để chạy mô hình minh họa."
        else:
            prediction = self.pred.predict(values)
            result.update(prediction=prediction,imputed=[k for k,v in zip(FIELDS,values) if v is None])
            result["trace"].append("PredictionAgent")
            if profile.get("explain"):
                result["reference_score"], result["effects"] = self.pred.explain(values)
            action = 0
            if rule=="R4":
                state,action = self.plan.choose(prediction["label"],values[5],profile.get("active",False))
                result["state"] = state
                result["trace"].append("PlannerAgent")
            result["topic"] = TOPICS[action]
            result["answer"],result["evidence"],result["answer_mode"] = self.kb.respond(QUERIES[action],TOPICS[action])
            if rule=="R3":
                result["answer"] = "Kết quả OGTT cần được trao đổi với nhân viên y tế. "+result["answer"]
            result["trace"].extend(["KnowledgeAgent", "Answerer", "CitationVerifier"])
        result["trace"].append("Coordinator")
        return result

