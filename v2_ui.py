"""HTML views for the MAS v2 response, metrics, contracts and API guide."""
from html import escape
import json

STATUS = {"ok": "Hoàn tất", "needs_review": "Cần xem lại", "degraded": "Đang chạy dự phòng", "invalid": "Cần sửa dữ liệu"}
def text(value):
    return escape(str(value))

def trace_table(rows):
    content = "".join(f"<tr><td>{text(r['agent'])}</td><td>{text(r['status'])}</td><td>{r['elapsed_ms']:.2f}</td><td>{text(r.get('error') or '—')}</td></tr>" for r in rows)
    return '<div class="table"><table><thead><tr><th>Tác tử</th><th>Trạng thái</th><th>Thời gian (ms)</th><th>Lỗi</th></tr></thead><tbody>'+content+'</tbody></table></div>'

def report_details(result):
    flags = "".join(f"<li><b>{text(f['id'])}</b> {text(f['text'])}"
                    + (f" [{text(f['source'])}]" if f.get("source") else "") + "</li>" for f in result["flags"])
    audit = result["audit"]
    explanation = '<details class="v2-details" open><summary>Cờ luật và điều kiện cần xem lại</summary><ul>'+flags+'</ul><small>Luật học thuật chưa được chuyên gia y tế duyệt.</small></details>'
    explanation += '<details class="v2-details"><summary>Đường đi và thời gian của tác tử</summary>' + trace_table(audit["agents"]) + '</details>'
    paths = "".join("<li>"+text(" → ".join(h["path"]))+f" [{text(h['id'])}]</li>"
                    for h in result["evidence"] if h.get("path"))
    explanation += '<details class="v2-details"><summary>Đồ thị bằng chứng</summary><ul>'+paths+'</ul><p>Mỗi cạnh dẫn đến đoạn và URL gốc trong danh sách nguồn.</p></details>'
    explanation += f'<p class="request-id">Mã lượt <code>{text(result["request_id"])}</code> · {audit["elapsed_ms"]:.1f} ms</p>'
    explanation += '<details class="v2-details"><summary>Xuất kết quả JSON</summary><p>Kết quả của lượt này có thể sao chép từ khung dưới.</p><textarea readonly aria-label="Kết quả JSON" rows="7">'+text(json.dumps(result,ensure_ascii=False,indent=2))+'</textarea></details>'
    return f'<p class="status-pill" role="status">{STATUS[result["status"]]} · DiaAgent v2</p>'+explanation

def monitoring_page(page, engine):
    stats = engine.monitor.metrics()
    contracts = "".join(f'<tr><td>{text(c["agent"])}</td><td>{text(c["input"])}</td><td>{text(c["output"])}</td></tr>' for c in engine.contracts())
    return page("Giám sát hệ đa tác tử", "Tổng hợp trạng thái, thời gian và hợp đồng của phiên bản v2.",
        f'<section class="panel"><h2>Vận hành</h2><div class="prediction-pair"><div><span>Số lượt trong bộ nhớ</span><strong>{stats["requests"]}</strong></div>'
        f'<div><span>Thời gian trung bình</span><strong>{stats["average_ms"]:.1f} ms</strong></div></div>'
        f'<p>{text(stats["statuses"])}</p><p>Lỗi ghi audit: {stats["audit_write_errors"]}. Giữ tối đa 500 lượt metadata.</p>'
        '<p>Nhật ký chỉ chứa mã lượt, trạng thái, thời gian và phiên bản. Bộ nhớ Render miễn phí có thể đặt lại khi khởi động lại.</p></section>'
        '<section class="panel"><h2>Các tác tử và hợp đồng</h2><div class="table"><table><tr><th>Tác tử</th><th>Đầu vào</th><th>Đầu ra</th></tr>'+contracts+'</table></div></section>'
        '<section class="panel"><h2>API v2</h2><p>POST /api/assess · POST /api/ask · GET /api/health · GET /api/model-card · GET /api/agents · GET /api/metrics · GET /api/trace/{request_id} · POST /api/simulate</p>'
        '<p>POST nhận application/json. /api/assess nhận {"profile": {...}, "question": "..."}. /api/ask nhận {"question": "...", "context": "K02"}.</p>'
        '<p>API mô phỏng chỉ dùng trạng thái và phần thưởng tổng hợp. Có thể gửi {"episodes": 3000, "seed": 42} đến /api/simulate.</p></section>')

