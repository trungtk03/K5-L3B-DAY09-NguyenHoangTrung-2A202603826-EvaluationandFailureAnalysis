# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Bảng phân tích chi tiết

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID `R-seeded_regression-C-002-s11` trong `reports/eval_seeded_regression.json` |
| Triệu chứng | Grader `pass_rate` (lab8 trial_pass) fail: `status resolved != denied`; grader `refund_amount_correct` fail: `refund_vnd 20000 != expected 0`; grader `db_fact_kept` fail. Reply: `"Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."` trong khi ledger ghi nhận hoàn 20.000đ (nhãn kỳ vọng: refund = 0, status = denied). |
| Bước sai đầu tiên | Event 3: `model_override` `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Các bước trước đó gồm Event 1 (`handoff`) và Event 2 (`investigator`: `lookup_order` truy vấn DB thành công với `order_id="O-202"`, `delay_days=2`, `shipping_fee_vnd=20000`) đều hoàn toàn chính xác. Event 2 đã trích xuất đúng sự thật khách quan từ DB. Đến Event 3, agent mới thực hiện ghi đè số ngày giao trễ từ 2 thành 5 theo lời khai trong ticket của khách hàng. |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng `C-002@11` trên shape `fixed`: Sau Event 2 (`investigator`), agent giữ nguyên dữ liệu DB `delay_days=2`, chuyển thẳng sang Event 3 (`quote`: `amount_vnd=0`, `reason="no_entitlement"`), không có event `model_override`. Kết quả từ chối hoàn tiền đúng theo chính sách (chỉ hoàn phí khi trễ ≥ 3 ngày). |
| Regression test | Evaluator `DbFactKept` và `RefundAmountCorrect` (đã có unit test `test_override_event_breaks_db_fact` và `test_wrong_amount_in_ledger` trong `tests/test_lab9_graders.py`). Đã xác nhận: fail trên `seeded_regression C-002@11` (`db_fact_kept=False`, `refund_amount_correct=False`) và pass trên `fixed C-002@11` (`db_fact_kept=True`, `refund_amount_correct=True`). |
| Chưa chắc chắn | Trace ghi nhận rõ event `model_override` trong pipeline nhưng không chứng minh được cơ chế nội tâm của LLM (là do prompt instruction ưu tiên ticket text hay do attention của mô hình bị đánh lạc hướng bởi văn phong khẩn nài của khách hàng). |

## Quy tắc áp dụng
- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" dẫn số event cụ thể (Event 3 `model_override`), không phỏng đoán mơ hồ.
- Regression test chạy độc lập và xác nhận bắt được lỗi trên biến thể hồi quy.
