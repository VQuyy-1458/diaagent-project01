from agents import Coordinator, PredictionAgent, TOPICS, QUERIES, read, words
from large_model import clean, encode, LABS


class LargeCoordinator(Coordinator):
    def __init__(self, *, use_neo4j=True):
        super().__init__(use_neo4j=use_neo4j)
        self.models = {name: PredictionAgent(model) for name, model in read("results/large_model.json").items()}

    def predict_profile(self, values, name):
        predictor = self.models[name]
        return predictor.predict(encode(values, predictor.model["fields"]))

    def run(self, profile):
        if profile.get("urgent") or not profile.get("scope"):
            return super().run(profile)
        values = clean(profile)
        name = "full" if all(field in values for field in LABS) else "screening"
        prediction = self.predict_profile(values, name)
        state, action = self.plan.choose(prediction["label"], values["bmi"], profile.get("active", False))
        topic = TOPICS[action]
        answer, evidence, mode = self.kb.respond(QUERIES[action], topic)
        result = dict(rule="R4", state=state, topic=topic, prediction=prediction, model_name=name,
                      answer=answer, evidence=evidence, answer_mode=mode,
                      trace=["SafetyAgent","PredictionAgent","PlannerAgent","KnowledgeAgent","CitationVerifier"])
        if profile.get("explain"):
            reference = self.models[name].model["reference"]
            result["effects"] = sorted(
                [(field, prediction["score"] - self.predict_profile(dict(values, **{field: baseline}), name)["score"])
                 for field,baseline in reference.items()], key=lambda item: -abs(item[1]))
        return result

    def compare(self, profile, field, new_value):
        values = clean(profile)
        if field not in ("bmi", "blood_glucose_level") or field not in values:
            raise ValueError("Chọn BMI hoặc glucose đã có trong hồ sơ để so sánh.")
        name = "full" if all(item in values for item in LABS) else "screening"
        if field in LABS and name == "screening":
            raise ValueError("Cần đủ hai xét nghiệm để so sánh glucose.")
        return self.predict_profile(values, name), self.predict_profile(clean(dict(profile, **{field:new_value})), name)

    def ask_detail(self, question, *, allow_external=False, context=""):
        answer, hits, mode = super().ask_detail(question, allow_external=allow_external, context=context)
        if mode != "Trích đoạn có kiểm chứng":
            return answer, hits, mode
        primary = hits[0]
        related = [doc for doc in hits[1:] if doc["score"] >= primary["score"] * .75]
        selected = [primary, *related]
        return "\n\n".join(f'{doc["text"]} [{doc["id"]}]' for doc in selected), selected, mode
