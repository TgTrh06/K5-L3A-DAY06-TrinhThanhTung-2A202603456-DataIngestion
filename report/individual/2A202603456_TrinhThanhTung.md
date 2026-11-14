# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline

- Chủ đề: truy xuất kiến thức từ giáo trình Nhập môn Xã hội học.
- Corpus: *Introduction to Sociology 3e*, OpenStax / Rice University; giấy phép CC BY-NC-SA 4.0. PDF được tải ngày 2026-11-13; manifest tại `data/manifest.md`.
- Phạm vi: 56 trang PDF trích được từ chương 5 (129–147), chương 6 (155–171), chương 7 (181–200). Số trang là số vật lý trong PDF. Dùng `pypdf`, chuẩn hóa Unicode, giữ `text`, `layout_text`, trang và chapter. Không trang nào trong phạm vi bị bỏ do thiếu text.
- Embedding: Sentence Transformers local, `sentence-transformers/all-MiniLM-L6-v2`, 384 chiều, vector chuẩn hóa; không gọi API, chi phí embedding $0.
- Vector store: PostgreSQL 16 + pgvector 0.8.7, cosine distance, exact search; filter metadata JSONB theo `chapter`.
- Lệnh trích xuất: `python scripts/extract_corpus.py` (từ `starter/`). Lệnh benchmark dev: `python -m src.run`; test holdout: `python -m src.run --split test`.
- Metadata chunk: `document_id`, `source`, `page`, `chapter`; chapter lấy từ phạm vi chương đã kiểm chứng.

## Cấu hình và benchmark

- A: fixed-size 500 ký tự, overlap 50.
- B: heading-aware, tối đa 500 ký tự, giữ ranh giới trang.
- C: dùng đúng index/chunk của B; chỉ lọc `chapter` khi câu hỏi cung cấp filter trước truy xuất.
- Benchmark có 20 câu, 15 dev / 5 test, gồm 5 câu có filter (3 dev, 2 test); evidence được kiểm tra trong trang gold trước khi chạy.
- Tiêu chí chọn đã đặt trước khi xem test: so sánh Hit@1 và Evidence Hit@3 trên dev; dùng test để báo holdout sau khi đã cố định A/B/C. Do dev cho thấy B và C cùng điểm retrieval, chưa có căn cứ chọn riêng B hay C bằng metric này; C có thêm ràng buộc phạm vi khi câu hỏi nêu chương.

## Kết quả retrieval

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Embed time (s) | Store time (s) | Cost |
|---|---|---:|---:|---:|---:|---:|---:|
| A | dev | 5/15 | 8/15 | 403 | 7.04 | 0.28 | $0 |
| B | dev | 10/15 | 11/15 | 434 | 5.41 | 0.31 | $0 |
| C | dev | 10/15 | 11/15 | 434 (B index) | same as B | same as B | $0 |
| A | test | 5/5 | 5/5 | 403 | 7.04 | 0.28 | $0 |
| B | test | 5/5 | 5/5 | 434 | 5.41 | 0.31 | $0 |
| C | test | 5/5 | 5/5 | 434 (B index) | same as B | same as B | $0 |

Thời gian embedding/lưu là thời gian cục bộ ghi trong metadata của lượt chạy; test run dựng lại index nên có thể khác nhẹ. Tổng retrieval dev: A 0.392 s, B 0.343 s, C 0.367 s. Tổng retrieval test: A 0.147 s, B 0.114 s, C 0.112 s. Số chunk A trung bình 469.2 ký tự (min 65, max 500); B trung bình 395.0 (min 30, max 500).

## Kết quả audit thủ công

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0.7/2 (10 vị trí) | 15/15 | N/A | 0=0, 1=0, 2=5 → 2.0/2 |
| B | 0.8/2 (10 vị trí) | 15/15 | N/A | 0=0, 1=0, 2=5 → 2.0/2 |
| C | 0.8/2 (10 vị trí) | 15/15 | 6/6 | 0=0, 1=0, 2=5 → 2.0/2 |

Nhãn audit: 90 hàng trong `starter/results/manual_audit.csv` (15 grounding + 45 metadata + 30 coherence). Reviewer: Trinh Thanh Tung. Phương pháp: đọc trace và evidence quote đối chiếu trực tiếp với chunk và trang nguồn PDF; metadata đối chiếu với `corpus_pages.jsonl`; filter kiểm tra cho các câu hỏi C có chapter filter. Audit hoàn thành và xác nhận bởi Trinh Thanh Tung ngày 2026-11-14.

Coherence: 10 vị trí trang × 3 chiến lược = 30 nhãn. Điểm phân bố A: 0×4, 1×5, 2×1; B/C: 0×4, 1×4, 2×2. Các trang điểm 0 (132, 138, 143, 166) là các trang bắt đầu bằng continuation fragment từ trang trước.

Metadata — tính hữu dụng: field `chapter` cho phép C lọc kết quả theo đúng chương mà câu hỏi chỉ định trước khi truy xuất, giúp loại các chunk cùng chủ đề nhưng thuộc chương khác (ví dụ: câu về bureaucracy của chương 6 không nhận chunk về deviance của chương 7). Hạn chế: `chapter` chỉ có 3 giá trị phân biệt trong corpus này; không lọc được ở mức section nhỏ hơn trong cùng chương; giá trị filter phải do câu hỏi cung cấp trước, không tự suy từ query.

## Phân tích và kết luận

- A–B: trên dev, B tăng Hit@1 từ 5/15 lên 10/15 và Evidence Hit@3 từ 8/15 lên 11/15. Trên test, cả hai đều 5/5; test nhỏ không phân biệt được cấu hình. Cơ chế: fixed-size cắt theo số ký tự cố định nên evidence quote thường bị chia đôi giữa hai chunk liền nhau — ví dụ q06, A trả về chunk `fixed-0002` chứa evidence nhưng bị ghép với nội dung từ đoạn trước trong cùng trang; B trả về chunk `heading-0002` giữ nguyên đoạn "Denmark gap year" thành một unit hoàn chỉnh nên score cosine cao hơn và hit rank 1. Heading-aware giữ ranh giới ngữ nghĩa tự nhiên của đoạn/section, giúp evidence ít bị cắt đôi hơn so với cửa sổ ký tự cố định.
- B–C: metric tổng trùng nhau trên dev/test. Filter có ích để giới hạn phạm vi câu hỏi có chapter, nhưng hai câu test có filter không tạo khác biệt điểm so với B vì B đã trả đúng chunk trong chương đó ở rank 1. Không suy rộng kết quả này ra corpus khác.
- Ví dụ lỗi dev: q16 hỏi các yếu tố ảnh hưởng việc một hành động bị gắn nhãn deviant; top-3 B không lấy đủ gold evidence ở trang 183. q18 hỏi khác biệt crime/deviance; top-3 B không lấy gold định nghĩa ở trang 194. Đây là lỗi evidence retrieval, dù có thể có chunk chủ đề gần đó.
- Kết quả test 5/5 cho mỗi chiến lược chỉ áp dụng cho 5 câu đã chọn; không chứng minh độ chính xác tổng quát. Cách chia theo heading dựa vào layout PDF và có thể chưa khôi phục chính xác mọi đoạn.
- Hạn chế: corpus chỉ là ba chương của một sách tiếng Anh; mẫu test nhỏ; coherence lấy opening passage tại 10 trang đã chọn, không đại diện cho toàn corpus.
- Nếu làm lại hoặc mở rộng: (1) thử chunking cross-page để xử lý continuation fragment — 4 trang điểm coherence 0 đều bắt đầu giữa chừng một câu từ trang trước, ranh giới trang cứng là nguyên nhân chính; (2) mở rộng benchmark sang các chương khác để kiểm tra generalization, tránh kết quả test 5/5 bị ảnh hưởng bởi câu hỏi dễ; (3) thêm metadata `section` ở cấp nhỏ hơn chapter (ví dụ theo heading cấp 2) để C có thể filter chính xác hơn với corpus lớn hơn.