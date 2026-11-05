import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIELDS = "Pregnancies Glucose BloodPressure SkinThickness Insulin BMI DPF Age".split()
ZERO_MISSING = set(FIELDS[1:6])
TOPICS = ["Xét nghiệm", "Dinh dưỡng", "Vận động", "Theo dõi"]
QUERIES = ["xét nghiệm a1c ogtt", "dinh dưỡng đĩa ăn nước lọc",
           "vận động thể lực đi bộ", "theo dõi đường huyết triệu chứng"]
BOUNDS = [(0,20),(1,250),(1,150),(1,110),(1,900),(1,80),(0,3),(21,100)]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def words(text):
    text = unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
    return re.findall(r"[a-z0-9]+", "".join(c for c in text if not unicodedata.combining(c)))


def graph():
    docs = read("data/kb.json")
    if not os.getenv("NEO4J_URI"):
        return docs, "Đồ thị JSON"
    from neo4j import GraphDatabase
    with GraphDatabase.driver(os.environ["NEO4J_URI"],
                              auth=(os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"])) as driver:
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
        records, _, _ = driver.execute_query("""
            MATCH (p:P1Passage)-[:ABOUT]->(t:P1Topic),
                  (p)-[:FROM_SOURCE]->(s:P1Source)
            RETURN p.id AS id, p.title AS title, p.text AS text, p.keys AS keys,
                   t.name AS topic, s.url AS url, s.name AS source ORDER BY id
            """, **options)
    return [dict(row) for row in records], "Neo4j"


class KnowledgeAgent:
    def __init__(self, docs):
        self.docs = docs
        counts = [Counter(words(d["title"]+" "+(d["keys"]+" ")*3+d["text"])) for d in docs]
        freq = Counter(term for c in counts for term in c)
        self.idf = {term: 1+math.log((1+len(docs))/(1+n)) for term,n in freq.items()}
        self.vectors = [self.vector(c) for c in counts]

    def vector(self, counts):
        weights = {t:(1+math.log(n))*self.idf[t] for t,n in counts.items() if t in self.idf}
        norm = math.sqrt(sum(v*v for v in weights.values())) or 1
        return {t:v/norm for t,v in weights.items()}

    def answer(self, question, topic=None):
        q = self.vector(Counter(words(question)))
        hits = []
        for d,v in zip(self.docs,self.vectors):
            if topic and d["topic"] != topic:
                continue
            score = sum(w*v.get(t,0) for t,w in q.items())
            if score >= .12:
                hits.append(dict(d, score=round(score,4)))
        hits.sort(key=lambda d: (-d["score"],d["id"]))
        hits = hits[:3]
        answer = " ".join(f'{d["text"]} [{d["id"]}]' for d in hits)
        return answer or "Kho tri thức chưa tìm thấy đoạn đủ phù hợp.", hits


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
            value = None if raw in ("",None) else float(raw)
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
        score = 1/(1+math.exp(-max(-60,min(60,h[0]))))
        return dict(score=score,label=int(score>=m["threshold"]),threshold=m["threshold"])


class PlannerAgent:
    def __init__(self, q):
        self.q = q

    def choose(self, label, bmi, active):
        state = 4*label + 2*int(bmi>=30) + int(not active)
        return state, max(range(4),key=self.q[state].__getitem__)


class Coordinator:
    def __init__(self):
        docs,self.backend = graph()
        self.kb = KnowledgeAgent(docs)
        self.pred = PredictionAgent(read("results/model.json"))
        self.plan = PlannerAgent(read("results/q.json"))

    def emergency(self):
        return ("Dấu hiệu đã chọn có thể cần xử trí khẩn cấp. Hãy liên hệ dịch vụ cấp cứu tại nơi bạn ở hoặc đến khoa cấp cứu ngay. [K01]",
                [d for d in self.kb.docs if d["id"]=="K01"])

    def ask(self, question):
        query = " ".join(words(question))
        if any(p in query for p in ("kho tho","bat tinh","hon me","non lien tuc","ketone cao","tho mui trai cay")):
            return self.emergency()
        if any(p in query for p in ("lieu insulin","tang lieu","giam lieu","ngung thuoc")):
            return "Hãy trao đổi với nhân viên y tế phụ trách điều trị về liều hoặc thay đổi thuốc.",[]
        return self.kb.answer(question)

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
            action = 0
            if rule=="R4":
                state,action = self.plan.choose(prediction["label"],values[5],profile.get("active",False))
                result["state"] = state
                result["trace"].append("PlannerAgent")
            result["topic"] = TOPICS[action]
            result["answer"],result["evidence"] = self.kb.answer(QUERIES[action],TOPICS[action])
            if rule=="R3":
                result["answer"] = "Kết quả OGTT cần được trao đổi với nhân viên y tế. "+result["answer"]
            result["trace"].append("KnowledgeAgent")
        result["trace"].append("Coordinator")
        return result

