\
    # api/webhook.py
    import os
    import json
    import datetime
    from flask import Flask, request, jsonify
    import requests
    from sqlalchemy import create_engine, Column, Integer, String, Date, Float
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker

    # --- CONFIG ---
    ZALO_BOT_TOKEN = os.environ.get("ZALO_BOT_TOKEN")  # đặt trên Vercel env
    DATABASE_URL = os.environ.get("DATABASE_URL")  # nếu không có: dùng sqlite file (dev only)

    if not DATABASE_URL:
        # file sqlite trong /tmp cho dev (ephemeral on Vercel)
        DATABASE_URL = "sqlite:////tmp/zalo_bot_db.sqlite3"

    ZALO_OA_MESSAGE_API = "https://openapi.zalo.me/v2.0/oa/message"

    # --- DB SETUP ---
    Base = declarative_base()
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    class Expense(Base):
        __tablename__ = "expenses"
        id = Column(Integer, primary_key=True, index=True)
        user_id = Column(String, index=True)
        amount = Column(Float)
        category = Column(String, default="khác")
        date = Column(Date)

    Base.metadata.create_all(bind=engine)

    # --- APP ---
    app = Flask(__name__)


    def send_text_to_user(user_id, text):
        """Gửi tin nhắn text tới user qua Zalo OA API"""
        if not ZALO_BOT_TOKEN:
            app.logger.error("No ZALO_BOT_TOKEN set")
            return
        payload = {
            "recipient": {"user_id": user_id},
            "message": {"text": text}
        }
        headers = {"Content-Type": "application/json"}
        params = {"access_token": ZALO_BOT_TOKEN}
        try:
            r = requests.post(ZALO_OA_MESSAGE_API, params=params, headers=headers, json=payload, timeout=8)
            app.logger.info("send message response: %s %s", r.status_code, r.text)
            return r
        except Exception as e:
            app.logger.error("Error sending message: %s", e)
            return None

    def parse_add_command(text):
        """
        Dự đoán lệnh thêm chi tiêu.
        Format gợi ý:
          chi 12000 an trua
          add 50000 cafe
          - 12000 ăn trưa
        Trả về (amount, category)
        """
        text = text.strip().lower()
        words = text.replace(",", "").split()
        amount = None
        category = "khác"
        for w in words:
            # tìm số nguyên
            if w.isdigit():
                amount = float(w)
                break
            # dạng có ký tự số + ký tự (vd 12k, 12.5k)
            if w.endswith("k") and w[:-1].replace(".", "", 1).isdigit():
                amount = float(w[:-1]) * 1000
                break
            # try float
            try:
                val = float(w)
                amount = val
                break
            except:
                pass
        # category: dùng phần còn lại (từ sau số)
        if amount is not None:
            # tìm index số trong words
            idx = None
            for i,w in enumerate(words):
                test = w.replace("k","").replace(".","")
                if test.isdigit() or w.isdigit():
                    idx = i
                    break
                try:
                    float(w)
                    idx = i
                    break
                except:
                    pass
            if idx is not None and idx+1 < len(words):
                category = " ".join(words[idx+1:])
        return amount, category

    def add_expense(user_id, amount, category, date=None):
        db = SessionLocal()
        if date is None:
            date = datetime.date.today()
        e = Expense(user_id=user_id, amount=amount, category=category, date=date)
        db.add(e)
        db.commit()
        db.close()
        return e

    def get_month_summary(user_id, year, month):
        db = SessionLocal()
        start = datetime.date(year, month, 1)
        if month == 12:
            end = datetime.date(year+1, 1, 1)
        else:
            end = datetime.date(year, month+1, 1)
        q = db.query(Expense).filter(Expense.user_id == user_id, Expense.date >= start, Expense.date < end)
        total = sum([e.amount for e in q]) if q.count() > 0 else 0
        by_cat = {}
        for e in q:
            by_cat[e.category] = by_cat.get(e.category, 0) + e.amount
        db.close()
        return {"total": total, "by_category": by_cat}

    @app.route("/api/webhook", methods=["GET", "POST"])
    def webhook():
        """
        Xử lý webhook từ Zalo. Khi user nhắn tin, Zalo sẽ POST payload ở dạng JSON.
        Mục tiêu: parse message text, lưu chi tiêu hoặc trả về thống kê.
        """
        data = request.get_json(force=True, silent=True)
        app.logger.info("incoming payload: %s", json.dumps(data, ensure_ascii=False))
        if not data:
            return jsonify({"status": "ok"})
        # Lấy user id và text nếu có
        try:
            sender = data.get("sender") or {}
            user_id = sender.get("user_id") or data.get("sender_id") or None
            message = data.get("message") or {}
            text = message.get("text", "").strip()
        except Exception as e:
            app.logger.error("Cannot parse incoming body: %s", e)
            return jsonify({"status": "ok"})

        if not user_id:
            return jsonify({"status": "ok"})

        text_lower = (text or "").lower()

        # /start
        if text_lower.startswith("/start") or text_lower.startswith("hi") or text_lower.startswith("hello"):
            reply = (
                "Chào bạn! Mình là bot lưu chi tiêu.\\n\\n"
                "Cách dùng:\\n"
                "- Ghi chi tiêu: gửi tin nhắn dạng `chi 12000 an trua` hoặc `12000 cafe`.\\n"
                "- Thống kê tháng hiện tại: gửi `thong ke` hoặc `stats`.\\n"
                "- So sánh tháng: gửi `so sanh 2025-10 2025-09` (format YYYY-MM).\\n"
                "- Xem tháng cụ thể: `thong ke 2025-10`.\\n"
            )
            send_text_to_user(user_id, reply)
            return jsonify({"status": "ok"})

        # Thêm chi tiêu
        if text_lower.startswith("chi") or text_lower.startswith("add") or (len(text_lower)>0 and text_lower[0].isdigit()) or text_lower.startswith("-"):
            amount, category = parse_add_command(text_lower)
            if amount is None:
                send_text_to_user(user_id, "Không nhận diện được số tiền. Vui lòng gửi lại theo dạng `chi 12000 an trua`.")
                return jsonify({"status":"ok"})
            add_expense(user_id=user_id, amount=amount, category=category)
            send_text_to_user(user_id, f"Đã lưu: {int(amount)} VND — {category}")
            return jsonify({"status":"ok"})

        # Thống kê đơn giản
        if text_lower.startswith("thong ke") or text_lower.startswith("stats") or text_lower.startswith("thống kê"):
            parts = text_lower.split()
            if len(parts) >= 2:
                try:
                    year, month = parts[1].split("-")
                    year = int(year); month = int(month)
                except:
                    year = datetime.date.today().year
                    month = datetime.date.today().month
            else:
                today = datetime.date.today()
                year, month = today.year, today.month
            summary = get_month_summary(user_id, year, month)
            total = int(summary["total"]) if summary["total"] is not None else 0
            by_cat = summary["by_category"]
            s = f"Thống kê {year}-{month:02d}:\\nTổng: {total} VND\\nTheo loại:\\n"
            for c, v in by_cat.items():
                s += f"- {c}: {int(v)} VND\\n"
            send_text_to_user(user_id, s)
            return jsonify({"status":"ok"})

        # So sánh hai tháng: "so sanh 2025-10 2025-09"
        if text_lower.startswith("so sanh") or text_lower.startswith("so sánh") or text_lower.startswith("compare"):
            parts = text_lower.split()
            if len(parts) >= 3:
                m1 = parts[1]
                m2 = parts[2]
                try:
                    y1, mo1 = map(int, m1.split("-"))
                    y2, mo2 = map(int, m2.split("-"))
                    s1 = get_month_summary(user_id, y1, mo1)
                    s2 = get_month_summary(user_id, y2, mo2)
                    t1 = s1["total"] or 0
                    t2 = s2["total"] or 0
                    diff = t1 - t2
                    pct = (diff / t2 * 100) if t2 != 0 else None
                    reply = f"So sánh {m1} vs {m2}:\\n- {m1}: {int(t1)} VND\\n- {m2}: {int(t2)} VND\\n- Chênh lệch: {int(diff)} VND\\n"
                    if pct is not None:
                        reply += f"- Tăng/Giảm: {pct:.1f}%\\n"
                    else:
                        reply += "- Không thể tính % (tháng so sánh bằng 0)\\n"
                    send_text_to_user(user_id, reply)
                except Exception as e:
                    send_text_to_user(user_id, "Sai định dạng. Dùng: `so sanh YYYY-MM YYYY-MM` (ví dụ: so sanh 2025-10 2025-09).")
            else:
                send_text_to_user(user_id, "Thiếu tham số. Dùng: `so sanh YYYY-MM YYYY-MM`.")
            return jsonify({"status":"ok"})

        # default: hướng dẫn
        send_text_to_user(user_id, "Mình không hiểu. Gửi /start để xem hướng dẫn.")
        return jsonify({"status":"ok"})


    # health\n    @app.route("/api/health", methods=["GET"])\n    def health():\n        return jsonify({\"status\":\"ok\"})\n\n    if __name__ == '__main__':\n        # Local debug server\n        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)\
