# DiaAgent Project 01 v2

Demo: https://diaagent-project01-quyntv699.onrender.com/

V2 tích hợp đặc tả Hybrid Multiagent System của môn học. Coordinator điều phối PatientDataAgent, DLPredictionAgent, RuleBasedAgent, KGRAGAgent, ExplanationAgent và MonitoringAgent. RLAgent chỉ được gọi ở mô phỏng.

## Chạy

Cài requirements.txt, chạy python app.py rồi mở http://localhost:8000.
Không có NEO4J_URI thì chạy snapshot JSON và ghi trạng thái dự phòng.
Có Neo4j thì đặt NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD và tùy chọn NEO4J_DATABASE.
Ứng dụng nạp data/DB_diabet.cypher trước khi đọc kho hiện hành.
Render tự khởi động Neo4j cùng web theo render_start.py.

## API

- POST /api/assess với {"profile":{...},"question":"..."}.
- POST /api/ask với {"question":"...","context":"K02"}.
- GET /api/health, /api/model-card, /api/agents, /api/metrics.
- GET /api/trace/{request_id} chỉ trả metadata, không trả hồ sơ.
- POST /api/simulate với {"seed":42,"episodes":3000}.

Các POST dùng Content-Type application/json. Hồ sơ cần scope=true, gender, age, hypertension, heart_disease, smoking_history, bmi. Hai xét nghiệm tùy chọn là HbA1c_level và blood_glucose_level. glucose_timing nhận unknown, fasting hoặc random. glucose_unit nhận mg/dL hoặc mmol/L. BMI để trống có thể tính từ height_cm và weight_kg.

## Hành vi

- Ca khẩn cấp dừng trước mô hình.
- Hồ sơ sai trả lỗi. Giá trị hữu hạn ngoài miền train được gắn cờ và dừng suy luận.
- Thiếu một trong hai xét nghiệm dùng screening, vẫn giữ xét nghiệm có sẵn cho luật.
- Cờ mâu thuẫn kích hoạt một lượt truy xuất tập trung vào ngưỡng.
- Giải thích gồm kết quả mô hình, cờ luật và bằng chứng. Có thể cấu hình GEMINI_API_KEY cho hỏi đáp có sự đồng ý, mặc định dùng đoạn đã biên soạn.
- Nhật ký metadata giữ tối đa 500 lượt, không ghi câu hỏi, điểm hay giá trị hồ sơ. Lưu trữ trên Render free là tạm thời và có thể mất khi redeploy.

## Kiểm chứng và notebook

Tại bản đầy đủ trên máy, chạy python qa/evaluate_v2.py, python qa/check_cypher_v2.py và python qa/check_v2_api.py.
Dùng python build_v2_notebook.py để tái tạo notebook kiểm thử và hình v2.
Notebook mô hình kế thừa nằm trong Project_01_Diabetes_Large.ipynb.
Báo cáo v2 nằm trong Project_01_Bao_cao_v2.docx.

V2 kế thừa hai MLP của v1, không huấn luyện lại. Model card ghi cấu hình, ngưỡng, nguồn Kaggle, phiên bản trọng số và độ đo trên 14.420 mẫu test. Kho gồm 20 đoạn Long Châu và 3 đoạn CDC, trong đó 2 đoạn ngưỡng được bổ sung ở v2.

