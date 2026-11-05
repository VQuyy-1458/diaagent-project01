"""Project 01 demo. Forms are request-local and the app does not store submissions."""
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from agents import Coordinator, FIELDS, read

engine = Coordinator()
stats = read("results/summary.json")
ROOT = Path(__file__).resolve().parent
CSS = (ROOT/"style.css").read_text(encoding="utf-8")
DEMO = dict(zip(FIELDS, ["2","138","72","29","","33.2","0.40","45"]))
LABELS = ["Số lần mang thai","Glucose 2 giờ OGTT · mg/dL","Huyết áp tâm trương · mmHg",
          "Nếp gấp da · mm","Insulin 2 giờ · µU/mL","BMI · kg/m²","Chỉ số phả hệ Pima","Tuổi · năm"]


def page(title, description, content):
    return f"""<!doctype html><html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | DiaAgent</title><style>{CSS}</style><body>
<header><a class="brand" href="/">DiaAgent <small>PROJECT 01</small></a>
<nav><a href="/">Phân tích</a><a href="/tri-thuc">Tri thức</a><a href="/thuc-nghiem">Thực nghiệm</a></nav></header>
<main><div class="hero"><div class="eyebrow">PHÁT TRIỂN CÁC HỆ THỐNG THÔNG MINH</div>
<h1>{title}</h1><p>{description}</p></div>
<div class="notice">Bản demo học thuật dùng hồ sơ giả định. Kết quả mô hình chỉ phục vụ minh họa và không thay thế đánh giá y tế.</div>
{content}<footer>PTIT · Project 01 &nbsp; / &nbsp; Nguồn tri thức: {engine.backend}</footer></main></body></html>"""


def evidence(hits):
    return "".join(f'<li><a href="{escape(h["url"])}" rel="noreferrer">{h["id"]} · {escape(h["title"])}</a>'
                   f'<br><small>{escape(h["source"])}</small></li>' for h in hits)


def analysis(values=None):
    fields = values if values is not None else dict(DEMO,scope=True)
    inputs = "".join(f'<label>{label}<input type="number" step="any" name="{k}" value="{escape(str(fields.get(k,"")))}"></label>'
                     for k,label in zip(FIELDS,LABELS))
    checks = "".join(f'<label class="check"><input type="checkbox" name="{k}" {"checked" if fields.get(k) else ""}> {label}</label>'
                     for k,label in [("scope","Hồ sơ giả định phù hợp phạm vi Pima"),
                                     ("active","Có vận động thường xuyên"),
                                     ("urgent","Có dấu hiệu nghiêm trọng như khó thở hoặc nôn liên tục")])
    panel = '<div class="panel"><span class="tag">LUỒNG AGENT</span><h2>Kết quả phân tích</h2><p>Chạy hồ sơ demo để xem điểm mô hình, luật được kích hoạt và nguồn trích dẫn.</p></div>'
    if values is not None:
        try:
            result = engine.run(fields)
            p = result["prediction"]
            score = (f'<div class="score">{p["score"]:.1%}</div><p>Lớp minh họa <b>{p["label"]}</b> · Ngưỡng {p["threshold"]:.2f}</p>'
                     if p else "")
            imputed = ", ".join(result.get("imputed", []))
            panel = (f'<div class="panel {"alert" if result["rule"]=="R0" else ""}"><span class="tag">LUẬT {result["rule"]}</span>'
                     f'<h2>{result["topic"] or "Kết quả kiểm tra hồ sơ"}</h2>{score}<p>{escape(result["answer"])}</p>'
                     + (f'<p><small>Biến điền trung vị: {escape(imputed)}</small></p>' if imputed else "")
                     + f'<ul>{evidence(result["evidence"])}</ul><hr><h3>Vết điều phối</h3>'
                     + '<div class="flow">' + "".join(f'<span>{a}</span>' for a in result["trace"]) + '</div></div>')
        except ValueError as error:
            panel = f'<div class="panel alert"><h2>Kiểm tra dữ liệu</h2><p>{escape(str(error))}</p></div>'
    return page("Hệ đa tác tử hỗ trợ đái tháo đường","Mô hình học sâu, luật an toàn và tri thức có nguồn trong một luồng phân tích.",
                f'<div class="columns"><form class="panel" method="post"><span class="tag">HỒ SƠ GIẢ ĐỊNH</span><h2>Dữ liệu đầu vào</h2>'
                f'<div class="fields">{inputs}</div>{checks}<button>Chạy phân tích</button></form>{panel}</div>')


def knowledge(values=None):
    question = values.get("question","") if values else ""
    answer = ""
    if question:
        message,hits = engine.ask(question)
        answer = f'<h2>Phản hồi có nguồn</h2><p>{escape(message)}</p><ul>{evidence(hits)}</ul>'
    return page("Hỏi đáp tri thức","Tra cứu đoạn tóm lược từ CDC và sách Diabetes in America.",
                f'<div class="panel"><form method="post"><label>Câu hỏi<input name="question" maxlength="300" '
                f'value="{escape(question)}" placeholder="Ví dụ: Xét nghiệm HbA1c phản ánh bao lâu?"></label>'
                f'<button>Tra cứu</button></form>{answer}</div>'
                f'<div class="panel"><h2>Kho tri thức</h2><p>{len(engine.kb.docs)} đoạn · {engine.backend}</p>'
                f'<ul>{evidence(engine.kb.docs)}</ul></div>')


def experiments():
    rows = "".join(f'<tr><th>{name}</th>'+ "".join(f'<td>{m[k]:.3f}</td>' for k in
                   ["auc","ap","recall","precision","f1","brier"])+'</tr>' for name,m in stats["models"].items())
    items = [("Hồ sơ Pima",stats["n"]),("Mẫu test",stats["split"][2]),
             ("Hit@3",f'{stats["rag"]["hit3"]:.0%}'),("Reward mô phỏng",f'{stats["rl"]["learned"]:.3f}')]
    cards = "".join(f'<div class="panel"><small>{k}</small><div class="score">{v}</div></div>' for k,v in items)
    return page("Kết quả thực nghiệm","Số liệu được xuất từ notebook đã chạy trên tập dữ liệu Pima.",
                f'<div class="cards">{cards}</div><div class="panel"><h2>Đánh giá trên tập test</h2><div class="table">'
                f'<table><tr><th>Mô hình</th><th>ROC-AUC</th><th>AP</th><th>Recall</th><th>Precision</th><th>F1</th><th>Brier</th></tr>'
                f'{rows}</table></div><p>Ngưỡng chọn trên validation. Reward mô phỏng phục vụ đánh giá PlannerAgent.</p></div>')


class Handler(BaseHTTPRequestHandler):
    def respond(self, data, kind="text/html; charset=utf-8", status=200):
        payload = data.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",kind)
        self.send_header("Content-Length",str(len(payload)))
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path=="/health":
            return self.respond('{"status":"ok"}',"application/json")
        pages = {"/":analysis,"/tri-thuc":knowledge,"/thuc-nghiem":experiments}
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
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","8000"))),Handler).serve_forever()

