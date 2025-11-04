# Zalo Expense Bot

Dự án Python Flask chạy trên Vercel giúp bạn lưu chi tiêu, thống kê và so sánh giữa các tháng qua Zalo OA Bot.

## Hướng dẫn cài đặt

1. Đặt các file như cấu trúc dự án.
2. Deploy lên Vercel.
3. Trong Vercel Project Settings → Environment Variables, thêm:
   - `ZALO_BOT_TOKEN` = (token của bot Zalo OA của bạn)
   - `DATABASE_URL` = (tùy chọn, PostgreSQL URL nếu muốn lưu lâu dài)

Webhook endpoint: `https://<your-vercel-app>.vercel.app/api/webhook`

## Cách dùng
- Gửi `/start` để nhận hướng dẫn.
- Gửi `chi 12000 an trua` để lưu chi tiêu.
- Gửi `thong ke` để xem tổng kết tháng.
- Gửi `so sanh 2025-10 2025-09` để so sánh chi tiêu giữa hai tháng.
