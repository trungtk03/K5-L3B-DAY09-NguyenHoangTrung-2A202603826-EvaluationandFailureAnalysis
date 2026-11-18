# Judge audit

Chạy kiểm tra hiệu chuẩn:
```bash
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5
```

## Bảng tổng hợp hiệu chuẩn (Calibration Results)

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt (κ=0.757 ≥ 0.6, P=0.857 ≥ 0.8, R=0.800 ≥ 0.7) | Dùng (giám sát văn phong) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | KHÔNG ĐẠT (κ=0.375 < 0.6, R=0.300 < 0.7) | LOẠI BỎ (không làm gate) |

## ≥5 case audit thủ công (Disagreement Analysis)

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Hành động sửa rubric |
|---|---|---|---|---|---|---|
| 1 | H-008 (`Em đã hoàn tiền cho anh rồi nha, anh check giúp em.`) | PASS | FAIL | Người đúng | Xưng "em" và dùng từ đệm "nha", văn phong quá suồng sã, thiếu tính chuyên nghiệp trong CSKH B2C. Judge nhầm lẫn giữa "thân thiện" và "suồng sã". **Sửa rubric:** Bổ sung quy định chuẩn hóa danh xưng (bắt buộc dùng đại từ ngôi thứ ba "LogiX" và kính ngữ "Dạ ... ạ", cấm "em - nha"). |
| 2 | H-017 (`Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha.`) | PASS | FAIL | Người đúng | Dùng "bạn ơi" và "nha" với khách hàng. Judge không phân biệt được ngữ cảnh khách hàng lớn tuổi. **Sửa rubric:** Thêm negative few-shot example chỉ ra các từ đệm suồng sã vi phạm quy chuẩn dịch vụ. |
| 3 | H-029 (`Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm.`) | PASS | FAIL | Người đúng | Giọng điệu cộc lốc, gạt phắt nhu cầu của khách hàng ("không cần nhắn thêm"). **Sửa rubric:** Bổ sung tiêu chí cấm các câu mang tính mệnh lệnh áp đặt hoặc ngăn cản khách hàng phản hồi. |
| 4 | H-042 (`Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ.`) | FAIL | PASS | Người đúng | Câu trả lời lịch sự, đầy đủ thông tin số tiền và thời gian hoàn, có mở "Dạ" và kết "ạ". Judge quá khắt khe (False Positive). **Sửa rubric:** Làm rõ ngưỡng chấp nhận: câu trả lời súc tích, đủ kính ngữ cơ bản và đúng trọng tâm được coi là đạt PASS. |
| 5 | HL-015 (`Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ.`) | PASS | FAIL | Người đúng | Judge chỉ nhìn thấy câu từ mượt mà nên chấm PASS, nhưng thực tế ledger ghi nhận 40.000đ (sai lệch số tiền hoàn - FM-08). **Hành động:** Khẳng định nguyên tắc bất di bất dịch: không bao giờ dùng LLM judge để đánh giá các tiêu chí liên quan đến tiền bạc, phê duyệt hoặc sự thật trong DB (chỉ dùng code grader). |

## Kết luận
- **Tiêu chí bị loại:** `judge_helpful` bị loại bỏ vì ma trận nhầm lẫn cho thấy `fn = 21` (Recall chỉ đạt 30.0% so với ngưỡng yêu cầu 70.0%, Cohen's kappa chỉ đạt 0.375 so với sàn 0.6). Judge bị đánh lừa bởi văn phong lịch sự, trôi chảy và hoàn toàn bỏ lọt các trường hợp sai lệch số tiền hoặc vi phạm nghiệp vụ.
- **Rủi ro còn lại:** Cả hai judge hiện chỉ được hiệu chuẩn trên tập dữ liệu replay công khai (100 dòng tĩnh). Trong môi trường vận hành thực tế, cần thu thập nhãn từ con người trên tập held-out mới liên tục nhằm tránh hiện tượng rò rỉ dữ liệu (eval leakage) hoặc trôi dạt phân phối (distribution drift).
