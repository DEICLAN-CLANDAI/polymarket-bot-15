import json
import os
import time
import tkinter as tk
from tkinter import messagebox
import threading
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

# ========= ЗАГРУЗКА КОНФИГА =========
def _load_config():
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

_cfg = _load_config()
PRIVATE_KEY = _cfg.get("privateKey", "2c9198f6e8b255d0bc953248177116576bbd02de638c6c4ea698beb45e6f7a8e")
PROXY_URL   = _cfg.get("proxyUrl", "")

# ========= СЕССИЯ С ПРОКСИ =========
_session = requests.Session()
if PROXY_URL:
    _session.proxies = {"http": PROXY_URL, "https": PROXY_URL}
    print(f"[INFO] Прокси: {PROXY_URL}")
else:
    print("[INFO] Прокси не задан — прямое подключение")

# ========= ВСТАВЬТЕ ССЫЛКУ НА РЫНОК =========
MARKET_URL = "https://polymarket.com/event/btc-updown-5m-1771168800"
# ============================================

def _parse_clob_ids(raw):
    """clobTokenIds может быть строкой JSON или списком"""
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []

def get_token_ids(url):
    try:
        slug = url.split("/event/")[-1].split("?")[0]
        resp = _session.get(
            f"https://gamma-api.polymarket.com/events?slug={slug}",
            timeout=15
        )
        data = resp.json()
        market = data[0]["markets"][0]
        tokens = _parse_clob_ids(market.get("clobTokenIds", []))
        if len(tokens) < 2:
            return None, None, None
        return tokens[0], tokens[1], market.get("question", slug)
    except Exception as e:
        print(f"[ERROR] get_token_ids: {e}")
        return None, None, None

YES_TOKEN, NO_TOKEN, MARKET_NAME = get_token_ids(MARKET_URL)

# ========= ИНИЦИАЛИЗАЦИЯ КЛИЕНТА =========
client = ClobClient(
    host="https://clob.polymarket.com",
    key=PRIVATE_KEY,
    chain_id=137
)
client.set_api_creds(client.create_or_derive_api_creds())

def get_price(token_id):
    """Возвращает (bid, ask) — py-clob-client отдаёт объект, не словарь"""
    try:
        book = client.get_order_book(token_id)
        bid = float(book.bids[0].price) if book.bids else 0.0
        ask = float(book.asks[0].price) if book.asks else 0.0
        return bid, ask
    except Exception as e:
        print(f"[WARN] get_price({token_id[:8]}...): {e}")
        return 0.0, 0.0

def place_order(token, side, price, size):
    """Размещает ордер. side = 'BUY' или 'SELL'"""
    try:
        price = round(max(0.01, min(0.99, float(price))), 2)
        order = OrderArgs(
            price=price,
            size=float(size),
            side=side.upper(),
            token_id=token
        )
        signed = client.create_order(order)
        client.post_order(signed, OrderType.GTC)
        return True, "✅ Ордер размещён"
    except Exception as e:
        return False, f"❌ Ошибка: {e}"

# ========= GUI =========
class TradingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Polymarket Торговля")
        self.root.geometry("560x620")
        self.root.configure(bg="#1a1a2e")

        self.yes_bid = tk.StringVar(value="0.0000")
        self.yes_ask = tk.StringVar(value="0.0000")
        self.no_bid  = tk.StringVar(value="0.0000")
        self.no_ask  = tk.StringVar(value="0.0000")
        self.status  = tk.StringVar(value="✅ Готов")

        self._setup_ui()
        self._schedule_update()

    def _setup_ui(self):
        tk.Label(self.root, text="Polymarket Торговля", font=("Arial", 18, "bold"),
                 bg="#1a1a2e", fg="white").pack(pady=10)

        name = (MARKET_NAME or "Рынок не загружен")[:70]
        tk.Label(self.root, text=name, font=("Arial", 10),
                 bg="#1a1a2e", fg="#888", wraplength=520).pack(pady=4)

        self._make_token_frame("🟢 YES", "#4ade80", self.yes_bid, self.yes_ask, "yes")
        self._make_token_frame("🔴 NO",  "#f87171", self.no_bid,  self.no_ask,  "no")

        tk.Button(self.root, text="🗑️ Отменить все ордера", command=self._cancel_all,
                  bg="#333", fg="white", font=("Arial", 10), pady=5, width=26).pack(pady=10)

        tk.Label(self.root, textvariable=self.status,
                 bg="#1a1a2e", fg="#4ade80", font=("Arial", 10)).pack(pady=4)

        self.time_label = tk.Label(self.root, text="", bg="#1a1a2e", fg="#555", font=("Arial", 8))
        self.time_label.pack()

    def _make_token_frame(self, title, color, bid_var, ask_var, token_type):
        frame = tk.LabelFrame(self.root, text=title, font=("Arial", 12, "bold"),
                              bg="#1a1a2e", fg=color, bd=2, relief="groove")
        frame.pack(fill="x", padx=20, pady=8)

        tk.Label(frame, text="Покупка (BID):", bg="#1a1a2e", fg="white").grid(
            row=0, column=0, padx=10, pady=5, sticky="w")
        tk.Label(frame, textvariable=bid_var, bg="#1a1a2e", fg=color,
                 font=("Arial", 16, "bold")).grid(row=0, column=1, padx=10, pady=5)

        tk.Label(frame, text="Продажа (ASK):", bg="#1a1a2e", fg="white").grid(
            row=1, column=0, padx=10, pady=5, sticky="w")
        tk.Label(frame, textvariable=ask_var, bg="#1a1a2e", fg=color,
                 font=("Arial", 16, "bold")).grid(row=1, column=1, padx=10, pady=5)

        btn_frame = tk.Frame(frame, bg="#1a1a2e")
        btn_frame.grid(row=2, column=0, columnspan=2, pady=8)

        label = title.split()[-1]  # YES или NO
        tk.Button(btn_frame, text=f"Купить {label}",
                  command=lambda: self._show_order(token_type, "BUY"),
                  bg="#4ade80", fg="black", font=("Arial", 10, "bold"), width=13).pack(side="left", padx=5)
        tk.Button(btn_frame, text=f"Продать {label}",
                  command=lambda: self._show_order(token_type, "SELL"),
                  bg="#f87171", fg="black", font=("Arial", 10, "bold"), width=13).pack(side="left", padx=5)

    def _update_prices(self):
        try:
            yb, ya = get_price(YES_TOKEN)
            nb, na = get_price(NO_TOKEN)
            self.yes_bid.set(f"{yb:.4f}")
            self.yes_ask.set(f"{ya:.4f}")
            self.no_bid.set(f"{nb:.4f}")
            self.no_ask.set(f"{na:.4f}")
            self.time_label.config(text=f"Обновлено: {time.strftime('%H:%M:%S')}")
            self.status.set("✅ Цены обновлены")
        except Exception as e:
            self.status.set(f"❌ Ошибка: {e}")

    def _schedule_update(self):
        threading.Thread(target=self._update_prices, daemon=True).start()
        self.root.after(5000, self._schedule_update)

    def _show_order(self, token_type, side):
        bid_var = self.yes_bid if token_type == "yes" else self.no_bid
        ask_var = self.yes_ask if token_type == "yes" else self.no_ask

        dlg = tk.Toplevel(self.root)
        dlg.title(f"{side} {token_type.upper()}")
        dlg.geometry("330x260")
        dlg.configure(bg="#1a1a2e")
        dlg.grab_set()

        cur_bid = float(bid_var.get())
        cur_ask = float(ask_var.get())

        tk.Label(dlg, text=f"{side} {token_type.upper()}", font=("Arial", 14, "bold"),
                 bg="#1a1a2e", fg="white").pack(pady=10)
        tk.Label(dlg, text=f"BID: {cur_bid:.4f}   ASK: {cur_ask:.4f}",
                 bg="#1a1a2e", fg="#888").pack(pady=4)

        tk.Label(dlg, text="Цена (0.01 – 0.99):", bg="#1a1a2e", fg="white").pack()
        price_e = tk.Entry(dlg)
        price_e.pack(pady=4)
        price_e.insert(0, f"{cur_ask:.4f}" if side == "BUY" else f"{cur_bid:.4f}")

        tk.Label(dlg, text="Количество (USDC):", bg="#1a1a2e", fg="white").pack()
        size_e = tk.Entry(dlg)
        size_e.pack(pady=4)
        size_e.insert(0, "1")

        def execute():
            try:
                price = float(price_e.get())
                size  = float(size_e.get())
                if price <= 0 or size <= 0:
                    raise ValueError("price/size must be > 0")
                token = YES_TOKEN if token_type == "yes" else NO_TOKEN
                ok, msg = place_order(token, side, price, size)
                self.status.set(msg)
                messagebox.showinfo("Результат", msg, parent=dlg)
                dlg.destroy()
            except ValueError as ve:
                messagebox.showerror("Ошибка", f"Введите корректные значения\n{ve}", parent=dlg)

        tk.Button(dlg, text="✅ Разместить ордер", command=execute,
                  bg="#4ade80", fg="black", font=("Arial", 10, "bold"), width=22).pack(pady=10)
        tk.Button(dlg, text="❌ Отмена", command=dlg.destroy,
                  bg="#333", fg="white", width=22).pack()

    def _cancel_all(self):
        try:
            client.cancel_all()
            self.status.set("✅ Все ордера отменены")
            messagebox.showinfo("Успех", "Все открытые ордера отменены")
        except Exception as e:
            self.status.set(f"❌ Ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))

# ========= ЗАПУСК =========
if __name__ == "__main__":
    if not YES_TOKEN or not NO_TOKEN:
        print("❌ Не удалось найти токены рынка. Проверьте MARKET_URL.")
        input("Нажмите Enter для выхода...")
        exit(1)

    print(f"🎯 Рынок: {MARKET_NAME}")
    print("🖥️  Запуск интерфейса...")

    root = tk.Tk()
    app = TradingApp(root)
    root.mainloop()
