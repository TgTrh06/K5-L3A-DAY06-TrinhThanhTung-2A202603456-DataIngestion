# Starter · PostgreSQL + pgvector

Bộ khởi động **tùy chọn** cho lab cá nhân. Docker Compose tạo PostgreSQL + pgvector local. Pipeline hiện có script trích xuất PDF, hai chiến lược chunking, embedding local bằng Sentence Transformers, lưu/truy xuất vector và chạy benchmark retrieval. Vẫn có thể chọn Qdrant, Chroma hoặc vector store tương đương theo [GUIDE.md](../GUIDE.md).

## Cấu trúc

```text
starter/
├── docker-compose.yml     # PostgreSQL 16 + pgvector, chỉ mở cổng local
├── init.sql               # bật extension khi tạo database mới
├── requirements.txt       # psycopg, pypdf, python-dotenv, sentence-transformers
├── .env.example           # cấu hình mẫu; copy thành .env
├── scripts/check_setup.py # kiểm tra kết nối và extension (đã chạy được)
├── src/
│   ├── models.py          # cấu trúc dữ liệu mẫu
│   ├── chunking.py        # fixed-size A và heading-aware B
│   ├── embeddings.py      # embedding model local
│   ├── store.py           # PostgreSQL + pgvector, cosine search, chapter filter
│   ├── evaluation.py      # Hit@1, Evidence Hit@3 và trace
│   └── run.py             # dựng index và chạy benchmark
├── scripts/extract_corpus.py # trích các trang PDF đã chọn thành JSONL
├── benchmark/questions.jsonl # câu hỏi, split và gold evidence
├── data/                  # bạn tự chuẩn bị corpus được phép sử dụng
└── results/               # lưu kết quả của bạn
```

## 1. Cài và kiểm tra database

Cần Docker Desktop hoặc Docker Engine + Compose, Python **3.11–3.14**, và mạng để tải image/dependencies lần đầu. Các lệnh sau chạy từ thư mục `starter/`:

```bash
cd starter
python3 -m venv .venv
```

Kích hoạt `.venv`: macOS/Linux dùng `source .venv/bin/activate`; Windows PowerShell dùng `.venv\Scripts\Activate.ps1`. Sau đó:

```bash
python -m pip install -r requirements.txt
# macOS/Linux: cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py
```

Kỳ vọng: hiện tên database, phiên bản PostgreSQL và pgvector, sau đó `Setup OK`. Đây **chỉ là kiểm tra hạ tầng**, không phải kết quả benchmark. Docker dùng cổng `127.0.0.1:55433` và mật khẩu cố định **chỉ dùng local cho lab**; nếu cổng bận, sửa đồng thời port trong `docker-compose.yml` và `DATABASE_URL` trong `.env`. `init.sql` chỉ chạy khi volume mới được tạo; nếu database sẵn có chưa bật extension, xem log Docker và kiểm tra cấu hình thay vì xóa volume chứa dữ liệu.

Dừng container nhưng giữ dữ liệu:

```bash
docker compose -p day6_student_starter stop
```

## 2. Embedding model

Mặc định dùng `sentence-transformers/all-MiniLM-L6-v2` chạy local, vector 384 chiều và không cần API key. Có thể chọn model khác tương thích Sentence Transformers qua `EMBEDDING_MODEL` trong `.env`; dùng cùng model cho mọi chiến lược và ghi tên, phiên bản, số chiều trong báo cáo. Không commit `.env`.

## 3. Hoàn thiện pipeline

1. Đặt corpus vào `data/` hoặc cung cấp manifest/hướng dẫn truy cập. Đọc [GUIDE.md](../GUIDE.md) về **30 trang nội dung**, quyền dữ liệu và metadata.
2. Hoàn thiện từng hàm TODO trong `src/`. Lưu ID tài liệu, nguồn, trang/vị trí và ít nhất một trường filter có ích.
3. Cấu hình A dùng fixed-size, B dùng heading-aware; C truy vấn đúng index B nhưng chỉ thêm filter chương khi câu hỏi cung cấp filter. Ba cấu hình giữ nguyên corpus, model và benchmark.
4. Bộ câu hỏi nằm ở `benchmark/questions.jsonl`; có 20 câu kèm evidence và split dev/test. Kiểm tra evidence trước khi chạy theo [BENCHMARK.md](../BENCHMARK.md).
5. Chạy pipeline từ thư mục `starter/`. Mặc định chỉ chạy dev để giữ test độc lập:

   ```bash
   python -m src.run
   ```

   Sau khi đã chọn và cố định cấu hình bằng dev, chạy test một lần riêng:

   ```bash
   python -m src.run --split test
   ```

   Trace JSONL, summary metric và metadata lượt chạy được ghi vào `results/`. Dùng `--split all` chỉ khi muốn chạy cả hai split trong cùng lượt và ghi rõ việc đó trong báo cáo.

Script trích xuất corpus đã chọn mặc định nằm ở `../data/introduction-sociology-3e_-_WEB.pdf`; chạy lại bằng `python scripts/extract_corpus.py`. Lưu code, cấu hình, kết quả và lệnh chạy để người chấm tái lập; không commit key, dữ liệu mật hoặc dữ liệu không có quyền chia sẻ.
