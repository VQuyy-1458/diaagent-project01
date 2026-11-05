"""Project 01 demo. Forms are request-local and the app does not store submissions."""
from html import escape
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from agents import FAQ, read
from large_agent import LargeCoordinator as Coordinator
from large_model import CATEGORIES, FIELDS

if __name__ == "__main__" and os.getenv("RENDER") == "true" and not os.getenv("NEO4J_URI"):
    from render_start import install_signal_handler, serve
    install_signal_handler()
    raise SystemExit(serve())

warming_neo4j = os.getenv("DIAAGENT_STARTING_DB") == "1"
engine = Coordinator(use_neo4j=not warming_neo4j)


def initialize_engine():
    global engine
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable

    deadline = time.monotonic() + 360
    try:
        with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=None, connection_timeout=2) as driver:
            while time.monotonic() < deadline:
                try:
                    driver.verify_connectivity()
                    break
                except ServiceUnavailable:
                    time.sleep(2)
            else:
                raise RuntimeError("Neo4j readiness timeout")
        engine = Coordinator()
        print("Neo4j knowledge base ready", flush=True)
    except Exception:
        import traceback
        traceback.print_exc()
        print("Neo4j initialization failed; serving the local graph snapshot", flush=True)

stats = read("results/large_metrics.json")
ROOT = Path(__file__).resolve().parent
CSS = (ROOT/"style.css").read_text(encoding="utf-8")
INTERFACE = (ROOT/"interface.js").read_text(encoding="utf-8")
DEMO = dict(zip(FIELDS, ["Female","54","0","0","No Info","27.32","6.6","140"]))
LABELS = ["Giới tính", "Tuổi", "Tăng huyết áp (0/1)", "Bệnh tim (0/1)", "Tiền sử hút thuốc",
          "BMI · kg/m²", "HbA1c · % (tùy chọn)", "Glucose máu · mg/dL (tùy chọn)"]
OPTIONS = {"Female":"Nữ","Male":"Nam","No Info":"Không có thông tin","never":"Chưa từng",
           "current":"Đang hút","former":"Đã bỏ","ever":"Từng hút","not current":"Hiện không hút"}


def profile_input(field, label, value):
    if field not in CATEGORIES:
        return f'<label>{label}<input type="text" inputmode="decimal" name="{field}" value="{escape(value)}"></label>'
    choices = "".join(f'<option value="{option}" {"selected" if option==value else ""}>{OPTIONS[option]}</option>'
                      for option in CATEGORIES[field])
    return f'<label>{label}<select name="{field}">{choices}</select></label>'



def page(title, description, content):
    return f"""<!doctype html><html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | DiaAgent</title><style>{CSS}</style><script src="/interface.js" defer></script><body>
<header><a class="brand" href="/">DiaAgent <small>PROJECT 01</small></a>
<nav><a href="/">Phân tích</a><a href="/tri-thuc">Hỏi đáp</a><a href="/faq">FAQ</a><a href="/tra-cuu">Tra cứu</a><a href="/thuc-nghiem">Thực nghiệm</a><button type="button" id="theme" aria-pressed="false">Sáng / tối</button></nav></header>
<main><div class="hero"><div class="eyebrow">PHÁT TRIỂN CÁC HỆ THỐNG THÔNG MINH</div>
<h1>{title}</h1><p>{description}</p></div>
<div class="notice">Bản demo học thuật dùng hồ sơ giả định. Kết quả mô hình chỉ phục vụ minh họa và không thay thế đánh giá y tế.</div>
{content}<footer>PTIT · Project 01 &nbsp; / &nbsp; Nguồn tri thức: {engine.backend}</footer></main></body></html>"""


def evidence(hits):
    items = []
    for hit in hits:
        path = hit.get("path")
        graph = f'<p class="graph-path">{escape(" → ".join(path))}</p>' if path else ""
        items.append(f'<li><a href="{escape(hit["url"])}" rel="noreferrer">'
                     f'{hit["id"]} · {escape(hit["title"])}</a><br><small>{escape(hit["source"])}</small>'
                     f'<details><summary>Xem bằng chứng</summary>{graph}<p>{escape(hit["text"])}</p></details></li>')
    return "".join(items)


def architecture_overview():
    backend = escape(engine.backend)
    return f"""<section class="panel architecture" aria-label="Kiến trúc Project 01">
    <div class="architecture-heading"><h2>Kiến trúc Project 01</h2>
    <span class="backend">Kho tri thức · {backend}</span></div>
    <ol class="architecture-steps">
      <li><b>01 · Dữ liệu và học sâu</b><span>Kaggle → MLP → dự đoán và phân loại</span></li>
      <li><b>02 · Điều phối</b><span>Luật an toàn + Q-learning → chọn chủ đề</span></li>
      <li><b>03 · Tri thức và trợ giúp</b><span>Web, sách → {backend} → truy xuất và kiểm tra trích dẫn</span></li>
    </ol></section>"""


def analysis(values=None):
    fields = values if values is not None else dict(DEMO,scope=True)
    inputs = "".join(profile_input(key,label,str(fields.get(key,""))) for key,label in zip(FIELDS,LABELS))
    checks = "".join(f'<label class="check"><input type="checkbox" name="{k}" {"checked" if fields.get(k) else ""}> {label}</label>'
                     for k,label in [("scope","Hồ sơ giả định dùng để minh họa mô hình"),
                                     ("active","Có vận động thường xuyên"),
                                     ("urgent","Có dấu hiệu nghiêm trọng như khó thở hoặc nôn liên tục")])
    panel = '<div class="panel"><span class="tag">LUỒNG AGENT</span><h2>Kết quả phân tích</h2><p>Chạy hồ sơ demo để xem điểm mô hình, luật được kích hoạt và nguồn trích dẫn.</p></div>'
    if values is not None:
        try:
            result = engine.run(fields)
            p = result["prediction"]
            score = (f'<div class="prediction-pair">'
                     f'<div><span>Dự đoán MLP</span><strong>{p["score"]:.1%}</strong><small>{'Đủ xét nghiệm' if result["model_name"]=="full" else 'Sàng lọc thiếu xét nghiệm'}</small></div>'
                     f'<div><span>Phân loại</span><strong>Lớp {p["label"]}</strong><small>Ngưỡng {p["threshold"]:.2f}</small></div>'
                     f'</div>' if p else "")
            comparison = ""
            if p and fields.get("compare_value"):
                try:
                    before, after = engine.compare(fields, fields.get("compare_field"), fields["compare_value"])
                    delta = (after["score"] - before["score"]) * 100
                    comparison = (f'<aside class="comparison"><h3>So sánh giả định</h3><p>{before["score"]:.1%}'
                                  f' → {after["score"]:.1%} ({delta:+.1f} điểm phần trăm), lớp '
                                  f'{before["label"]} → {after["label"]}. Các trường khác giữ nguyên.</p>'
                                  f'<small>Phản ứng của mô hình với đầu vào giả định.</small></aside>')
                except ValueError as exc:
                    comparison = f'<p class="notice">{escape(str(exc))}</p>'
            explanation = ""
            if "effects" in result:
                rows = "".join(f"<li>{escape(field)}: {effect * 100:+.1f} điểm phần trăm</li>"
                               for field, effect in result["effects"][:5])
                explanation = (f'<details open><summary>Độ nhạy từng biến</summary>'
                               f'<p>Thay riêng từng biến bằng giá trị tham chiếu từ tập train. '
                               f'Tối đa năm đóng góp lớn nhất theo trị tuyệt đối.</p>'
                               f'<ul>{rows}</ul><small>Chênh lệch điểm khi thay một biến. Các chênh lệch này không cộng thành điểm dự đoán.</small></details>')
            imputed = ", ".join(result.get("imputed", []))
            panel = (f'<div class="panel {"alert" if result["rule"]=="R0" else ""}"><span class="tag">LUẬT {result["rule"]}</span>'
                     f'<h2>{result["topic"] or "Kết quả kiểm tra hồ sơ"}</h2>{score}{comparison}{explanation}<p>{escape(result["answer"])}</p>'
                     + (f'<p><small>Biến điền trung vị: {escape(imputed)}</small></p>' if imputed else "")
                     + f'<ul>{evidence(result["evidence"])}</ul><hr><h3>Vết điều phối</h3>'
                     + '<div class="flow">' + "".join(f'<span>{a}</span>' for a in result["trace"]) + '</div></div>')
        except ValueError as error:
            panel = f'<div class="panel alert"><h2>Kiểm tra dữ liệu</h2><p>{escape(str(error))}</p></div>'
    explain = ('<label class="check"><input type="checkbox" name="explain" '
               f'{"checked" if fields.get("explain") else ""}> Giải thích đóng góp của các biến</label>')
    selected = " selected" if fields.get("compare_field") == "bmi" else ""
    value = escape(fields.get("compare_value", ""))
    what_if = ('<details class="what-if"><summary>Thử một giá trị giả định</summary>'
               '<label>Trường so sánh<select name="compare_field"><option value="blood_glucose_level">Glucose máu</option>'
               f'<option value="bmi"{selected}>BMI</option></select></label>'
               f'<label>Giá trị giả định<input name="compare_value" inputmode="decimal" value="{value}"></label></details>')
    return page("Hệ đa tác tử hỗ trợ đái tháo đường","Mô hình học sâu, luật an toàn và tri thức có nguồn trong một luồng phân tích.",
                f'{architecture_overview()}<div class="columns"><form class="panel" method="post"><span class="tag">HỒ SƠ GIẢ ĐỊNH</span><h2>Dữ liệu đầu vào</h2>'
                f'<div class="fields">{inputs}</div>{checks}{explain}{what_if}<button>Chạy phân tích</button></form>{panel}</div>')


def knowledge(values=None):
    question = values.get("question", "") if values else ""
    answer = ""
    if question.strip():
        context = values.get("context", "")
        message, hits, mode = engine.ask_detail(question, allow_external=values.get("external") == "on",
                                                context=context)
        context = hits[0]["id"] if hits and mode != "Luật an toàn" else ""
        answer = (f'<article id="current-answer" data-context="{context}"><h2>Phản hồi có nguồn</h2>'
                  f'<p><small>{escape(mode)}</small></p><p class="answer-text" style="white-space:pre-line">{escape(message)}</p>'
                  f'<ul>{evidence(hits)}</ul></article>')
    consent = ""
    if os.getenv("GEMINI_API_KEY"):
        consent = ('<label class="check"><input type="checkbox" name="external"> '
                   'Dùng Gemini để diễn giải. Chỉ nhập câu hỏi kiến thức chung.</label>')
    return page("Hỏi đáp tri thức", "Hỏi bằng tiếng Việt và xem đường dẫn từ khái niệm đến bằng chứng.",
                f'<div class="panel"><form id="knowledge-form" action="/tri-thuc" method="post">'
                f'<label>Câu hỏi<input name="question" maxlength="300" required value="{escape(question)}" '
                f'placeholder="Ví dụ: Xét nghiệm HbA1c phản ánh bao lâu?"></label>'
                f'{consent}<button type="submit">Tra cứu</button></form><p id="chat-status" role="status"></p>'
                f'<div id="answer-slot">{answer}</div></div>'
                '<details class="panel"><summary>Lịch sử hỏi đáp trên trình duyệt</summary>'
                '<p>Giữ tối đa 12 lượt trên trình duyệt này.</p><div id="conversation"></div>'
                '<button id="export-chat" type="button">Xuất hội thoại</button> '
                '<button id="clear-chat" type="button">Xóa hội thoại</button></details>')


def faq_page():
    docs = {doc["id"]: doc for doc in engine.kb.docs}
    cards = "".join(f'<details class="panel"><summary>{escape(question)}</summary>'
                    f'<p>{escape(docs[id_]["text"])}</p><ul>{evidence([docs[id_]])}</ul></details>'
                    for question,id_ in FAQ.items() if id_ in docs)
    return page("Câu hỏi thường gặp", "Mở một câu để xem đáp án đã biên soạn và nguồn.", cards)


def search_page(query, topic):
    topics = sorted({doc["topic"] for doc in engine.kb.docs})
    topic = topic if topic in topics else ""
    options = '<option value="">Tất cả chủ đề</option>' + "".join(
        f'<option {"selected" if item == topic else ""}>{escape(item)}</option>' for item in topics)
    hits = engine.kb.retrieve(query, topic or None) if query.strip() else [
        dict(doc, path=[edge["head"], edge["relation"], edge["tail"]]) if
        (edge := engine.kb.relations.get(doc["id"])) else doc
        for doc in engine.kb.docs if not topic or doc["topic"] == topic
    ]
    return page("Tra cứu kho tri thức", f"{len(engine.kb.docs)} đoạn nguồn · {engine.backend}",
                f'<div class="panel"><form action="/tra-cuu" method="get"><label>Từ khóa'
                f'<input name="q" maxlength="300" value="{escape(query)}"></label>'
                f'<label>Chủ đề<select name="topic">{options}</select></label><button>Tìm nguồn</button></form>'
                f'<h2>{len(hits)} kết quả</h2><ul>{evidence(hits)}</ul></div>')


def experiments():
    rows = "".join(f'<tr><th>{name}</th>'+ "".join(f'<td>{m[k]:.3f}</td>' for k in
                   ["auc","ap","f1","brier","threshold"])+'</tr>' for name,m in stats["models"].items())
    return page("Kết quả thực nghiệm","Diabetes Prediction Dataset",f"""
        <section class="panel"><h2>Đánh giá trên {stats['split'][2]:,} mẫu test</h2>
        <p>{stats['raw']:,} dòng gốc · {stats['clean']:,} dòng sau làm sạch.</p>
        <div class="table"><table><tr><th>MLP</th><th>ROC-AUC</th><th>AP</th><th>F1</th><th>Brier</th><th>Ngưỡng</th></tr>
        {rows}</table></div><p>full dùng đủ hai xét nghiệm. screening dùng sáu trường còn lại.</p></section>""")


class Handler(BaseHTTPRequestHandler):
    def respond(self, data, kind="text/html; charset=utf-8", status=200):
        payload = data.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",kind)
        self.send_header("Content-Length",str(len(payload)))
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        request = urlsplit(self.path)
        path = request.path
        if path == "/interface.js":
            return self.respond(INTERFACE, "text/javascript; charset=utf-8")
        if path=="/health":
            return self.respond(json.dumps({"status": "ok", "knowledge_backend": engine.backend}), "application/json")
        if path == "/tra-cuu":
            try:
                params = parse_qs(request.query, max_num_fields=8)
            except ValueError:
                return self.respond("Bộ lọc không hợp lệ.", "text/plain; charset=utf-8", 400)
            return self.respond(search_page(params.get("q", [""])[0][:300], params.get("topic", [""])[0]))
        pages = {"/":analysis,"/tri-thuc":knowledge,"/faq":faq_page,"/thuc-nghiem":experiments}
        if path not in pages:
            return self.respond("Không tìm thấy trang.","text/plain; charset=utf-8",404)
        self.respond(pages[path]())

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            size = int(self.headers.get("Content-Length",0))
            if not 0<size<=8192:
                raise ValueError
            fields = {k:v[-1] for k,v in parse_qs(self.rfile.read(size).decode("utf-8"),
                                                  keep_blank_values=True,max_num_fields=20).items()}
        except ValueError:
            return self.respond("Dữ liệu biểu mẫu không hợp lệ.","text/plain; charset=utf-8",400)
        if path=="/":
            self.respond(analysis(fields))
        elif path=="/tri-thuc":
            fields["question"] = fields.get("question","")[:300]
            self.respond(knowledge(fields))
        else:
            self.respond("Không tìm thấy trang.","text/plain; charset=utf-8",404)


if __name__=="__main__":
    if warming_neo4j:
        threading.Thread(target=initialize_engine, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","8000"))),Handler).serve_forever()

