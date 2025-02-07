########################################
# Monkey-patch: Locale ayarlarını güvenli hale getiriyoruz.
#########################################
import os
os.environ["LC_ALL"] = "C"
os.environ["LANG"] = "C"
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
import locale
_original_setlocale = locale.setlocale

def safe_setlocale(category, locale_str=None):
    try:
        return _original_setlocale(category, locale_str)
    except locale.Error:
        return _original_setlocale(category, "C")

locale.setlocale = safe_setlocale

#########################################
# Gerekli modüllerin import edilmesi
#########################################
import json
import subprocess
import threading
import time
import requests
import winreg  # Sadece Windows için
from io import BytesIO
from PIL import Image, ImageTk
import concurrent.futures
from tkinter import filedialog  # Tkinter'ın dosya seçme penceresi için
from tkinter import messagebox  # Mesaj kutuları için
from tkinter import simpledialog  # API key sorgulaması için

import webbrowser  # Link açmak için

# ttkbootstrap ile modern arayüz ve karanlık tema kullanıyoruz.
import ttkbootstrap as tb
from ttkbootstrap import ttk
from ttkbootstrap.constants import *

# Çalışan süreçleri kontrol etmek için ekliyoruz:
import psutil

#########################################
# Ana Sınıf: GameLauncher
#########################################
class GameLauncher:
    def __init__(self):
        self.api_key = ""
        # Launcher tarama fonksiyonlarını güncelliyoruz, Xbox da eklendi.
        self.launchers = {
            'Steam': self.scan_steam,
            'Epic Games': self.scan_epic_games,
            'GOG Galaxy': self.scan_gog,
            'Ubisoft Connect': self.scan_ubisoft,
            'Origin': self.scan_origin,
            'Xbox': self.scan_xbox_games
        }
        self.games = []         # Tarama sonucu + manuel eklenen oyunların birleşimi
        self.manual_games = []  # Manuel eklenen oyunlar (ayrı dosyada saklanıyor)
        self.error_logs = []    # Tarama sırasında oluşan hata mesajlarını toplayacağız
        self.load_settings()
        # Launcher istemci bilgileri (yol ve process adı)
        self.clients = {
            'Steam': {'path': self.get_steam_client_path(), 'process': 'steam.exe'},
            'Epic Games': {'path': self.get_epic_client_path(), 'process': 'EpicGamesLauncher.exe'},
            'GOG Galaxy': {'path': self.get_gog_client_path(), 'process': os.path.basename(self.get_gog_client_path()) if self.get_gog_client_path() else None},
            'Ubisoft Connect': {'path': self.get_ubisoft_client_path(), 'process': 'UbisoftConnect.exe'},
            'Origin': {'path': self.get_origin_client_path(), 'process': os.path.basename(self.get_origin_client_path()) if self.get_origin_client_path() else None}
        }
        
        # Karanlık tema "cyborg" ile modern pencere oluşturuyoruz.
        self.root = tb.Window(themename="cyborg")
        self.root.title("Game Launcher")
        self.root.geometry("1000x600")
        self.root.iconbitmap("./game.ico")

        # Stil ayarları
        style = ttk.Style()
        style.configure("Treeview", rowheight=30, font=('Segoe UI', 10))
        style.configure("Treeview.Heading", font=('Segoe UI', 11, 'bold'))

        self.create_widgets()
        self.load_manual_games()  # Manuel eklenen oyunları dosyadan yükle
        
        # Eğer API key girilmemişse, başta soruyoruz.
        if not self.api_key:
            key = simpledialog.askstring(
                "API Key Girişi",
                "GiantBomb API Key giriniz.\n(Eğer boş bırakılırsa, resim ve açıklama alınmayacak.)\nAPI key almak için: https://www.giantbomb.com/api/"
            )
            if key:
                self.api_key = key.strip()
                self.save_settings()
            else:
                messagebox.showwarning("Uyarı", "API key girilmedi. Resim ve açıklama alınmayacak.")
                self.api_key = ""

        self.load_manual_games()  # Manuel eklenen oyunları dosyadan yükle


        # Tarama sonuçlarını, eğer varsa, yükle; yoksa tarama yap.
        self.load_scan_results()
        if not self.games:
            self.threaded_scan_games()

        # Resim ve GiantBomb bilgileri, scan_results.json ile kalıcı olarak saklanıyor.
        threading.Thread(target=self.prefetch_images, daemon=True).start()
        
        # Şu an izlenen oyunun unique ID'sini tutmak için:
        self.current_monitored_game = None

    #########################################
    # Ayarlar: API Key Yükleme ve Kaydetme
    #########################################
    def load_settings(self):
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
            self.api_key = settings.get("api_key", "")
        except Exception:
            self.api_key = ""

    def save_settings(self):
        settings = {"api_key": self.api_key}
        with open("settings.json", "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)

    def open_api_key_settings(self):
        settings_win = tb.Toplevel(self.root)
        settings_win.title("API Key Ayarları")
        settings_win.grab_set()

        frm = ttk.Frame(settings_win, padding=10)
        frm.pack(fill='both', expand=True)

        ttk.Label(frm, text="GiantBomb API Key:").grid(row=0, column=0, padx=5, pady=5, sticky='e')
        api_entry = ttk.Entry(frm, width=40)
        api_entry.grid(row=0, column=1, padx=5, pady=5)
        api_entry.insert(0, self.api_key)

        # API key almak için link
        def open_link(event):
            webbrowser.open("https://www.giantbomb.com/api/")

        link_label = ttk.Label(frm, text="API key almak için tıklayın", foreground="blue", cursor="hand2")
        link_label.grid(row=1, column=0, columnspan=2, padx=5, pady=5)
        link_label.bind("<Button-1>", open_link)

        def save_api_key():
            self.api_key = api_entry.get().strip()
            self.save_settings()
            settings_win.destroy()

        save_btn = ttk.Button(frm, text="Kaydet", command=save_api_key, bootstyle=SUCCESS)
        save_btn.grid(row=2, column=1, padx=5, pady=10)

    
    #########################################
    # Steam manifest'larından appid bilgisini alma
    #########################################
    def get_steam_appid(self, manifest_dir, game_folder):
        import glob, re
        pattern = os.path.join(manifest_dir, "appmanifest_*.acf")
        for manifest_file in glob.glob(pattern):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    content = f.read()
                # Basit bir kontrol: "installdir" alanı game_folder ile eşleşiyor mu?
                if f'"installdir"\t"{game_folder}"' in content or f'"installdir"    "{game_folder}"' in content:
                    m = re.search(r'"appid"\s+"(\d+)"', content)
                    if m:
                        return m.group(1)
            except Exception as e:
                print("Error parsing manifest", manifest_file, e)
        return None

    #########################################
    # Scan Sonuçlarını Yükle / Kaydet
    #########################################
    def load_scan_results(self):
        try:
            with open("scan_results.json", "r", encoding="utf-8") as f:
                self.games = json.load(f)
            self.update_treeview(self.games)
        except Exception as e:
            print("Scan sonuçları yüklenemedi:", e)
            self.games = []

    def save_scan_results(self):
        try:
            with open("scan_results.json", "w", encoding="utf-8") as f:
                json.dump(self.games, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print("Scan sonuçları kaydedilirken hata:", e)

    #########################################
    # Arayüz Oluşturma
    #########################################
    def create_widgets(self):
        # Menü Çubuğu: Ayarlar menüsü ekleniyor.
        menu_bar = tb.Menu(self.root)
        self.root.config(menu=menu_bar)
        settings_menu = tb.Menu(menu_bar, tearoff=0)
        settings_menu.add_command(label="API Key Ayarları", command=self.open_api_key_settings)
        menu_bar.add_cascade(label="Ayarlar", menu=settings_menu)

        self.paned = ttk.Panedwindow(self.root, orient='horizontal')
        self.paned.pack(fill='both', expand=True, padx=10, pady=10)

        self.left_frame = ttk.Frame(self.paned)
        self.right_frame = ttk.Frame(self.paned, width=400)

        self.paned.add(self.left_frame, weight=3)
        self.paned.add(self.right_frame, weight=1)

        # Sol tarafta: Treeview (oyun listesi)
        self.tree = ttk.Treeview(self.left_frame, columns=('Name', 'Launcher', 'Path'), show='headings')
        self.tree.heading('Name', text='Oyun Adı')
        self.tree.heading('Launcher', text='Launcher')
        self.tree.heading('Path', text='Yol')
        self.tree.pack(fill='both', expand=True, padx=5, pady=5)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        btn_frame = ttk.Frame(self.left_frame)
        btn_frame.pack(pady=10)

        self.launch_btn = ttk.Button(btn_frame, text="Oyunu Başlat", command=self.launch_game, bootstyle=PRIMARY)
        self.launch_btn.grid(row=0, column=0, padx=5)

        self.add_btn = ttk.Button(btn_frame, text="Uygulama Ekle", command=self.add_application, bootstyle=SUCCESS)
        self.add_btn.grid(row=0, column=1, padx=5)

        self.edit_btn = ttk.Button(btn_frame, text="Düzenle", command=self.edit_game, bootstyle=INFO)
        self.edit_btn.grid(row=0, column=2, padx=5)

        self.delete_btn = ttk.Button(btn_frame, text="Oyunu Sil", command=self.delete_game, bootstyle=DANGER)
        self.delete_btn.grid(row=0, column=3, padx=5)

        self.refresh_btn = ttk.Button(btn_frame, text="Yenile", command=self.refresh, bootstyle=SECONDARY)
        self.refresh_btn.grid(row=0, column=4, padx=5)

        # Sağ tarafta: Önizleme paneli
        preview_label = ttk.Label(self.right_frame, text="Oyun Önizlemesi", font=('Segoe UI', 14, 'bold'))
        preview_label.pack(pady=10)

        self.preview_canvas = tb.Canvas(self.right_frame, width=400, height=300, background='#343a40', bd=0, highlightthickness=0)
        self.preview_canvas.pack(pady=10, anchor="n")

        self.info_label = ttk.Label(self.right_frame, text="", wraplength=380, justify="left")
        self.info_label.pack(pady=5, anchor="nw")
        
        self.status_label = ttk.Label(self.right_frame, text="", font=('Segoe UI', 10))
        self.status_label.pack(pady=5, anchor="nw")

    #########################################
    # Yenileme (Refresh) Metodu - Değişiklikleri saklama/sıfırlama sorusu ekleniyor.
    #########################################
    def refresh(self):
        if messagebox.askyesno("Değişiklikleri Kaydet", "Yenilemeden önce yaptığınız değişiklikleri saklamak istiyor musunuz?"):
            self.save_manual_games()
        else:
            self.load_manual_games()
        self.threaded_scan_games()

    #########################################
    # Treeview Seçiminde Önizleme Güncelleme
    #########################################
    def on_tree_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        unique_id = selected[0]
        game = self.get_game_by_unique(unique_id)
        if game:
            self.update_preview(game)

    def get_game_by_unique(self, unique):
        for game in self.games:
            if game.get('unique') == unique:
                return game
        return None

    #########################################
    # Önizleme Güncelleme: Resim ve GiantBomb Bilgileri
    #########################################
    def update_preview(self, game):
        self.preview_canvas.delete("all")
        # Önce resmi güncelleyelim:
        image_path = game.get('image', '')

        if (not image_path) and not game.get('image_attempted', False):
            self.preview_canvas.create_text(200, 150, text="Yükleniyor...", fill="white", font=('Segoe UI', 16))
            threading.Thread(
                target=lambda: (
                    self.prefetch_image_for_game(game),
                    self.root.after(0, lambda: self.update_preview(game))
                ),
                daemon=True
            ).start()
            return

        if image_path == "not_found":
            self.preview_canvas.create_text(200, 150, text="Resim Yok", fill="white", font=('Segoe UI', 16))
        else:
            try:
                if image_path.startswith("http"):
                    response = requests.get(image_path, timeout=5)
                    if response.status_code == 200:
                        img_data = BytesIO(response.content)
                        img = Image.open(img_data)
                    else:
                        print(f"HTTP Hatası {response.status_code} URL: {image_path}")
                        img = None
                else:
                    if os.path.exists(image_path):
                        img = Image.open(image_path)
                    else:
                        img = None
                if img:
                    img.thumbnail((400, 300))
                    self.preview_image = ImageTk.PhotoImage(img)
                    self.preview_canvas.create_image(200, 150, image=self.preview_image)
                else:
                    self.preview_canvas.create_text(200, 150, text="Resim Yok", fill="white", font=('Segoe UI', 16))
            except Exception as e:
                print(f"Önizleme resmi yüklenirken hata: {str(e)}")
                self.preview_canvas.create_text(200, 150, text="Resim Yok", fill="white", font=('Segoe UI', 16))

        # GiantBomb bilgilerini güncelleyelim:
        if game.get("giantbomb_info"):
            self.info_label.config(text=game["giantbomb_info"])
        else:
            if not game.get("info_attempted", False):
                game["info_attempted"] = True
                threading.Thread(
                    target=lambda: (
                        self.fetch_giantbomb_info(game),
                        self.root.after(0, lambda: self.update_preview(game))
                    ),
                    daemon=True
                ).start()
            else:
                self.info_label.config(text="Bilgi bulunamadı.")
                
        # Başlangıçta seçilen oyunun durumunu kontrol etmeye başlıyoruz:
        self.current_monitored_game = game['unique']
        self.monitor_game_status(game)

    #########################################
    # GiantBomb API ile Oyun Bilgisi Çekme
    #########################################
    def fetch_giantbomb_info(self, game):
        # API key girilmemişse, açıklama alınmayacağını belirtelim.
        if not self.api_key:
            game["giantbomb_info"] = "API key girilmedi. Resim ve açıklama alınmayacak."
            return
        try:
            url = "https://www.giantbomb.com/api/search/"
            params = {
                "api_key": self.api_key,
                "format": "json",
                "query": game.get("name", ""),
                "resources": "game",
                "limit": 1
            }
            headers = {"User-Agent": "GameLauncher/1.0"}
            response = requests.get(url, params=params, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                if results and len(results) > 0:
                    result = results[0]
                    deck = result.get("deck", "Açıklama yok.")
                    release_date = result.get("original_release_date", "Bilinmiyor")
                    detail_url = result.get("site_detail_url", "")
                    info_text = f"{deck}\nÇıkış Tarihi: {release_date}\nDetaylar: {detail_url}"
                    game["giantbomb_info"] = info_text
                    self.save_scan_results()
            else:
                print("HTTP Hatası", response.status_code, "giantbomb info aranırken", game.get("name", ""))
        except Exception as e:
            print(f"Error fetching giantbomb info for {game.get('name', '')}: {str(e)}")

    def sanitize_filename(self, filename):
        invalid_chars = '<>:"/\\|?*'
        for ch in invalid_chars:
            filename = filename.replace(ch, '_')
        return filename

    #########################################
    # Resim Önbellekleme (Prefetch) - Eşzamanlı
    #########################################
    def prefetch_images(self):
        cache_folder = "image_cache"
        if not os.path.exists(cache_folder):
            os.makedirs(cache_folder)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            for game in self.games:
                if game.get('source') == "manual" and game.get('image'):
                    continue
                image_path = game.get('image', '')
                if image_path and image_path.startswith(cache_folder) and os.path.exists(image_path):
                    continue
                futures.append(executor.submit(self.fetch_and_save_image, game, cache_folder))
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Error prefetching image: {str(e)}")

    def fetch_and_save_image(self, game, cache_folder):
        if game.get('next_request_time', 0) > time.time():
            return
        fetched_url = self.fetch_game_image_from_internet(game.get('name', ''))
        if fetched_url:
            try:
                response = requests.get(fetched_url, timeout=5)
                if response.status_code == 200:
                    local_filename = self.sanitize_filename(f"{game['unique']}.jpg")
                    local_path = os.path.join(cache_folder, local_filename)
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    game['image'] = local_path
                    game['image_attempted'] = True
                    if self.tree.selection() and self.tree.selection()[0] == game['unique']:
                        self.root.after(0, lambda: self.update_preview(game))
                else:
                    print(f"HTTP Hatası {response.status_code} indirirken {game.get('name', '')}")
                    game['image'] = "not_found"
                    game['image_attempted'] = True
                    game['next_request_time'] = time.time() + 30
            except Exception as e:
                print(f"Error downloading image for {game.get('name', '')}: {str(e)}")
                game['image'] = "not_found"
                game['image_attempted'] = True
                game['next_request_time'] = time.time() + 30
        else:
            game['image'] = "not_found"
            game['image_attempted'] = True
            game['next_request_time'] = time.time() + 30
    # GiantBomb API'den resim URL'si almak için metot:
    #########################################
    # GiantBomb API ile Oyun Resmi Çekme
    #########################################
    def fetch_game_image_from_internet(self, game_name):
        # API key girilmemişse, resim getirilmeyecek.
        if not self.api_key:
            return None
        try:
            url = "https://www.giantbomb.com/api/search/"
            params = {
                "api_key": self.api_key,
                "format": "json",
                "query": game_name,
                "resources": "game",
                "limit": 1
            }
            headers = {"User-Agent": "GameLauncher/1.0"}
            response = requests.get(url, params=params, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                if results and len(results) > 0:
                    image_info = results[0].get("image", {})
                    image_url = image_info.get("medium_url")
                    return image_url
            else:
                print("HTTP Hatası", response.status_code, "oyun resmi aranırken", game_name)
        except Exception as e:
            print(f"Error fetching image for {game_name}: {str(e)}")
        return None



    def prefetch_image_for_game(self, game):
        cache_folder = "image_cache"
        if not os.path.exists(cache_folder):
            os.makedirs(cache_folder)
        if game.get('next_request_time', 0) > time.time():
            return
        fetched_url = self.fetch_game_image_from_internet(game.get('name', ''))
        if fetched_url:
            try:
                response = requests.get(fetched_url, timeout=5)
                if response.status_code == 200:
                    local_filename = self.sanitize_filename(f"{game['unique']}.jpg")
                    local_path = os.path.join(cache_folder, local_filename)
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    game['image'] = local_path
                    game['image_attempted'] = True
                else:
                    print(f"HTTP Hatası {response.status_code} indirirken {game.get('name', '')}")
                    game['image'] = "not_found"
                    game['image_attempted'] = True
                    game['next_request_time'] = time.time() + 30
            except Exception as e:
                print(f"Error downloading image for {game.get('name', '')}: {str(e)}")
                game['image'] = "not_found"
                game['image_attempted'] = True
                game['next_request_time'] = time.time() + 30
        else:
            game['image'] = "not_found"
            game['image_attempted'] = True
            game['next_request_time'] = time.time() + 30

    #########################################
    # "Resmi Sıfırla" fonksiyonu, Düzenleme penceresinde kullanılacak
    #########################################
    def reset_image_in_edit(self, game, image_entry):
        game['image'] = ""
        if 'next_request_time' in game:
            del game['next_request_time']
        if 'image_attempted' in game:
            del game['image_attempted']
        image_entry.delete(0, 'end')
        threading.Thread(
            target=lambda: (
                self.prefetch_image_for_game(game),
                self.root.after(0, lambda: self.update_preview(game))
            ),
            daemon=True
        ).start()

    #########################################
    # Oyun Tarama ve UI Güncelleme (Arka Planda)
    #########################################
    def generate_unique_key(self, launcher, path, existing_keys):
        base = f"{launcher}_{path}"
        unique = base
        counter = 1
        while unique in existing_keys:
            unique = f"{base}_{counter}"
            counter += 1
        return unique

    def scan_games_thread(self):
        scanned_games = []
        used_keys = set()
        for launcher_name, scanner in self.launchers.items():
            try:
                games = scanner()
                for game in games:
                    game['launcher'] = launcher_name
                    game['source'] = 'scanned'
                    game['unique'] = self.generate_unique_key(launcher_name, game['path'], used_keys)
                    used_keys.add(game['unique'])
                scanned_games.extend(games)
            except Exception as e:
                err = f"{launcher_name} tarama hatası: {str(e)}"
                self.error_logs.append(err)
                print(err)
        manual_overrides = {g['unique']: g for g in self.manual_games if 'unique' in g}
        final_games = []
        for game in scanned_games:
            if game['unique'] in manual_overrides:
                final_games.append(manual_overrides[game['unique']])
            else:
                final_games.append(game)
        scanned_keys = {game['unique'] for game in scanned_games}
        for game in self.manual_games:
            if game['unique'] not in scanned_keys:
                final_games.append(game)
        # Deduplicate final_games by unique key
        deduped = {}
        for game in final_games:
            deduped[game['unique']] = game
        return list(deduped.values())

    def update_treeview(self, games):
        self.games = games
        self.tree.delete(*self.tree.get_children())
        for game in self.games:
            # Eğer aynı unique id ile kayıt varsa, atlamaya çalışalım.
            if not self.tree.exists(game['unique']):
                self.tree.insert('', 'end', iid=game['unique'], values=(game['name'], game.get('launcher', ''), game['path']))

    def threaded_scan_games(self):
        def task():
            games = self.scan_games_thread()
            self.games = games
            self.save_scan_results()
            if self.error_logs:
                try:
                    with open("scan_errors.json", "w", encoding="utf-8") as f:
                        json.dump(self.error_logs, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    print("Error saving scan errors:", e)
            self.root.after(0, lambda: self.update_treeview(games))
        threading.Thread(target=task, daemon=True).start()

    #########################################
    # Yeni: Oyunun çalışıp çalışmadığını kontrol eden metotlar
    #########################################
    def check_game_running(self, game):
        try:
            exe_name = os.path.basename(game['path']).lower()
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and proc.info['name'].lower() == exe_name:
                    return True
            return False
        except Exception as e:
            print("Error checking game running status:", e)
            return False

    def monitor_game_status(self, game, delay=5000):
        if self.current_monitored_game != game['unique']:
            return
        # Eğer launcher Steam veya Xbox ise, ilk 15 saniyede doğrudan "çalışıyor" diyelim.
        if game.get('launcher') in ("Steam", "Xbox"):
            launch_time = game.get('launch_time', 0)
            if time.time() - launch_time < 15:
                self.status_label.config(text="Oyun çalışıyor (başlatıldı, kontrol ediliyor...)")
                self.root.after(delay, lambda: self.monitor_game_status(game, delay))
                return
        running = self.check_game_running(game)
        if running:
            self.status_label.config(text="Oyun çalışıyor")
        else:
            self.status_label.config(text="Oyun kapalı")
        self.root.after(delay, lambda: self.monitor_game_status(game, delay))

    #########################################
    # Oyun Başlatma, Ekleme, Düzenleme, Silme İşlemleri
    #########################################
    def launch_game(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Uyarı", "Lütfen bir oyun seçin")
            return

        unique_id = selected[0]
        game = self.get_game_by_unique(unique_id)
        if not game:
            return

        launcher_name = game.get('launcher', '')
        game_path = game.get('path')
        print(f"Başlatılmaya çalışılan oyun yolu: {game_path}")

        # Eğer launcher Steam ise ve appid varsa:
        if launcher_name == "Steam" and game.get("appid"):
            game['launch_time'] = time.time()
            steam_client = self.clients.get("Steam", {}).get("path")
            if steam_client and os.path.exists(steam_client):
                try:
                    subprocess.Popen(["steam://rungameid/" + str(game["appid"])])
                    self.current_monitored_game = game['unique']
                    # 15 saniyelik gecikme: Steam'in oyunu başlatması için zaman tanıyacağız.
                    self.root.after(15000, lambda: self.monitor_game_status(game))
                    return
                except Exception as e:
                    print("Steam launcher ile oyunu başlatmada hata:", e)
            try:
                os.startfile("steam://rungameid/" + str(game["appid"]))
                game['launch_time'] = time.time()
                self.current_monitored_game = game['unique']
                self.root.after(15000, lambda: self.monitor_game_status(game))
                return
            except Exception as e:
                print("Steam protokolüyle başlatmada hata:", e)
        # Eğer launcher Epic Games ise ve appid varsa:
        if launcher_name == "Epic" and game.get("appid"):
            game['launch_time'] = time.time()
            epic_client = self.clients.get("Epic Games", {}).get("path")
            if epic_client and os.path.exists(epic_client):
                try:
                    subprocess.Popen(["com.epicgames.launcher://apps/" + str(game["appid"])])
                    self.current_monitored_game = game['unique']
                    self.root.after(15000, lambda: self.monitor_game_status(game))
                    return
                except Exception as e:
                    print("Epic Games launcher ile oyunu başlatmada hata:", e)
            try:
                subprocess.Popen(["com.epicgames.launcher://apps/" + str(game["appid"])])
                game['launch_time'] = time.time()
                self.current_monitored_game = game['unique']
                self.root.after(15000, lambda: self.monitor_game_status(game))
                return
            except Exception as e:
                print("Epic Games protokolüyle başlatmada hata:", e)
        # Xbox oyunları için:
        if launcher_name == "Xbox" and game.get("args"):
            try:
                # explorer.exe'yi argüman ile birlikte çağırıyoruz.
                subprocess.Popen([game['path'], game.get("args")])
                game['launch_time'] = time.time()
                self.current_monitored_game = game['unique']
                self.root.after(15000, lambda: self.monitor_game_status(game))
                return
            except Exception as e:
                messagebox.showerror("Hata", f"Xbox oyunu başlatılamadı: {str(e)}")
                return

        # Diğer durumlarda, doğrudan oyunun exe'si çalıştırılsın.
        try:
            subprocess.Popen(game_path, cwd=os.path.dirname(game_path))
            game['launch_time'] = time.time()
            self.current_monitored_game = game['unique']
            self.monitor_game_status(game)
        except Exception as e:
            messagebox.showerror("Hata", f"Oyun başlatılamadı: {str(e)}")
        # Diğer durumlarda oyun exe'si doğrudan çalıştırılsın.
        try:
            subprocess.Popen(game_path, cwd=os.path.dirname(game_path))
            game['launch_time'] = time.time()
            self.current_monitored_game = game['unique']
            self.monitor_game_status(game)
        except Exception as e:
            messagebox.showerror("Hata", f"Oyun başlatılamadı: {str(e)}")

    def add_application(self):
        add_win = tb.Toplevel(self.root)
        add_win.title("Uygulama Ekle")
        add_win.grab_set()

        frm = ttk.Frame(add_win, padding=10)
        frm.pack(fill='both', expand=True)

        ttk.Label(frm, text="Oyun Adı:").grid(row=0, column=0, padx=5, pady=5, sticky='e')
        name_entry = ttk.Entry(frm, width=40)
        name_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frm, text="Launcher:").grid(row=1, column=0, padx=5, pady=5, sticky='e')
        # Launcher seçeneklerine "Xbox" ve "Diğer" ekleniyor.
        launcher_options = ["", "Steam", "Epic Games", "GOG Galaxy", "Ubisoft Connect", "Origin", "Xbox", "Diğer"]
        launcher_var = tb.StringVar(value="")
        launcher_combo = ttk.Combobox(frm, textvariable=launcher_var, values=launcher_options, state='readonly')
        launcher_combo.grid(row=1, column=1, padx=5, pady=5)
        launcher_combo.current(0)

        ttk.Label(frm, text="Oyun Yolu:").grid(row=2, column=0, padx=5, pady=5, sticky='e')
        path_entry = ttk.Entry(frm, width=40)
        path_entry.grid(row=2, column=1, padx=5, pady=5)

        def browse_exe():
            file_path = filedialog.askopenfilename(filetypes=[("Executable files", "*.exe"), ("All files", "*.*")])
            if file_path:
                path_entry.delete(0, 'end')
                path_entry.insert(0, file_path)

        browse_exe_btn = ttk.Button(frm, text="Gözat", command=browse_exe, bootstyle=INFO)
        browse_exe_btn.grid(row=2, column=2, padx=5, pady=5)

        ttk.Label(frm, text="Resim (Dosya/URL):").grid(row=3, column=0, padx=5, pady=5, sticky='e')
        image_entry = ttk.Entry(frm, width=40)
        image_entry.grid(row=3, column=1, padx=5, pady=5)

        def browse_image():
            file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.gif"), ("All files", "*.*")])
            if file_path:
                image_entry.delete(0, 'end')
                image_entry.insert(0, file_path)

        browse_img_btn = ttk.Button(frm, text="Gözat", command=browse_image, bootstyle=INFO)
        browse_img_btn.grid(row=3, column=2, padx=5, pady=5)
        
        # Yeni: Oyun Bilgisi alanı
        ttk.Label(frm, text="Oyun Bilgisi:").grid(row=4, column=0, padx=5, pady=5, sticky='e')
        info_entry = ttk.Entry(frm, width=40)
        info_entry.grid(row=4, column=1, padx=5, pady=5)

        def save_app():
            name = name_entry.get().strip()
            launcher = launcher_var.get().strip()
            path = path_entry.get().strip()
            image = image_entry.get().strip()
            info = info_entry.get().strip()
            if not name or not path:
                messagebox.showwarning("Uyarı", "Lütfen oyun adını ve yolunu girin.")
                return
            existing_keys = set(self.tree.get_children())
            new_unique = self.generate_unique_key(launcher, path, existing_keys)
            new_game = {
                'name': name,
                'launcher': launcher,
                'path': path,
                'image': image,
                'giantbomb_info': info,
                'source': 'manual',
                'unique': new_unique
            }
            self.manual_games.append(new_game)
            self.save_manual_games()
            self.games.append(new_game)
            self.tree.insert('', 'end', iid=new_unique, values=(name, launcher, path))
            add_win.destroy()

        save_btn = ttk.Button(frm, text="Ekle", command=save_app, bootstyle=SUCCESS)
        save_btn.grid(row=5, column=1, padx=5, pady=10)


    def edit_game(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Uyarı", "Lütfen düzenlenecek oyunu seçin.")
            return
        unique_id = selected[0]
        game = self.get_game_by_unique(unique_id)
        if not game:
            return

        edit_win = tb.Toplevel(self.root)
        edit_win.title("Oyunu Düzenle")
        edit_win.grab_set()

        frm = ttk.Frame(edit_win, padding=10)
        frm.pack(fill='both', expand=True)

        ttk.Label(frm, text="Oyun Adı:").grid(row=0, column=0, padx=5, pady=5, sticky='e')
        name_entry = ttk.Entry(frm, width=40)
        name_entry.grid(row=0, column=1, padx=5, pady=5)
        name_entry.insert(0, game.get('name', ''))

        ttk.Label(frm, text="Launcher:").grid(row=1, column=0, padx=5, pady=5, sticky='e')
        launcher_options = ["", "Steam", "Epic Games", "GOG Galaxy", "Ubisoft Connect", "Origin", "Xbox", "Diğer"]
        launcher_var = tb.StringVar(value=game.get('launcher', ''))
        launcher_combo = ttk.Combobox(frm, textvariable=launcher_var, values=launcher_options, state='readonly')
        launcher_combo.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(frm, text="Oyun Yolu:").grid(row=2, column=0, padx=5, pady=5, sticky='e')
        path_entry = ttk.Entry(frm, width=40)
        path_entry.grid(row=2, column=1, padx=5, pady=5)
        path_entry.insert(0, game.get('path', ''))

        def browse_exe_edit():
            file_path = filedialog.askopenfilename(filetypes=[("Executable files", "*.exe"), ("All files", "*.*")])
            if file_path:
                path_entry.delete(0, 'end')
                path_entry.insert(0, file_path)

        browse_exe_btn = ttk.Button(frm, text="Gözat", command=browse_exe_edit, bootstyle=INFO)
        browse_exe_btn.grid(row=2, column=2, padx=5, pady=5)

        ttk.Label(frm, text="Resim (Dosya/URL):").grid(row=3, column=0, padx=5, pady=5, sticky='e')
        image_entry = ttk.Entry(frm, width=40)
        image_entry.grid(row=3, column=1, padx=5, pady=5)
        image_entry.insert(0, game.get('image', ''))

        def browse_image_edit():
            file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.gif"), ("All files", "*.*")])
            if file_path:
                image_entry.delete(0, 'end')
                image_entry.insert(0, file_path)

        browse_img_btn = ttk.Button(frm, text="Gözat", command=browse_image_edit, bootstyle=INFO)
        browse_img_btn.grid(row=3, column=2, padx=5, pady=5)

        reset_img_btn = ttk.Button(frm, text="Resmi Sıfırla", 
                                    command=lambda: self.reset_image_in_edit(game, image_entry), 
                                    bootstyle=WARNING)
        reset_img_btn.grid(row=3, column=3, padx=5, pady=5)
        
        # Yeni: Oyun Bilgisi alanı
        ttk.Label(frm, text="Oyun Bilgisi:").grid(row=4, column=0, padx=5, pady=5, sticky='e')
        info_entry = ttk.Entry(frm, width=40)
        info_entry.grid(row=4, column=1, padx=5, pady=5)
        info_entry.insert(0, game.get('giantbomb_info', ''))

        def save_edit():
            new_name = name_entry.get().strip()
            new_launcher = launcher_var.get().strip()
            new_path = path_entry.get().strip()
            new_image = image_entry.get().strip()
            new_info = info_entry.get().strip()
            if not new_name or not new_path:
                messagebox.showwarning("Uyarı", "Lütfen oyun adını ve yolunu girin.")
                return
            old_unique = game.get('unique')
            game['name'] = new_name
            game['launcher'] = new_launcher
            game['path'] = new_path
            game['image'] = new_image
            game['giantbomb_info'] = new_info
            existing_keys = set(self.tree.get_children())
            existing_keys.discard(old_unique)
            new_unique = self.generate_unique_key(new_launcher, new_path, existing_keys)
            game['unique'] = new_unique
            self.tree.delete(old_unique)
            self.tree.insert('', 'end', iid=new_unique, values=(new_name, new_launcher, new_path))
            updated = False
            for idx, g in enumerate(self.manual_games):
                if g.get('unique') == old_unique:
                    self.manual_games[idx] = game
                    updated = True
                    break
            if not updated:
                self.manual_games.append(game)
            self.save_manual_games()
            edit_win.destroy()
            self.update_preview(game)

        save_btn = ttk.Button(frm, text="Kaydet", command=save_edit, bootstyle=SUCCESS)
        save_btn.grid(row=5, column=1, padx=5, pady=10)


    def delete_game(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Uyarı", "Lütfen silinecek oyunu seçin.")
            return
        confirm = messagebox.askyesno("Onay", "Seçilen oyunu silmek istediğinize emin misiniz?")
        if not confirm:
            return

        unique_id = selected[0]
        self.games = [g for g in self.games if g.get('unique') != unique_id]
        self.manual_games = [g for g in self.manual_games if g.get('unique') != unique_id]
        self.save_manual_games()
        self.tree.delete(unique_id)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(200, 150, text="Resim Yok", fill="white", font=('Segoe UI', 16))
        self.info_label.config(text="")

    def refresh(self):
        if messagebox.askyesno("Değişiklikleri Kaydet", "Yenilemeden önce yaptığınız değişiklikleri saklamak istiyor musunuz?"):
            self.save_manual_games()
        else:
            self.load_manual_games()
        self.threaded_scan_games()

    def load_manual_games(self):
        try:
            with open("manual_games.json", "r", encoding="utf-8") as f:
                self.manual_games = json.load(f)
        except FileNotFoundError:
            self.manual_games = []

    def save_manual_games(self):
        with open("manual_games.json", "w", encoding="utf-8") as f:
            json.dump(self.manual_games, f, indent=4, ensure_ascii=False)

    #########################################
    # Launcher Tarama Fonksiyonları
    #########################################
    def scan_steam(self):
        games = []
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")
            steam_path = winreg.QueryValueEx(key, "InstallPath")[0].strip('"')
            library_folders = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
            with open(library_folders, 'r', encoding='utf-8') as f:
                data = f.read()
            paths = [steam_path]
            for line in data.splitlines():
                if '"path"' in line:
                    try:
                        path = line.split('"')[3].replace('\\\\', '\\').strip('"')
                        paths.append(path)
                    except IndexError:
                        continue
            for path in paths:
                apps_path = os.path.join(path, "steamapps", "common")
                if os.path.exists(apps_path):
                    for folder in os.listdir(apps_path):
                        game_path = os.path.join(apps_path, folder)
                        exe = self.find_exe(game_path)
                        if exe:
                            game = {'name': folder, 'path': exe}
                            game['image'] = self.find_game_image(exe) or ""
                            # Steam manifest'larından appid bilgisini alalım:
                            manifest_dir = os.path.join(path, "steamapps")
                            appid = self.get_steam_appid(manifest_dir, folder)
                            if appid:
                                game['appid'] = appid
                            games.append(game)
        except Exception as e:
            err = f"Steam tarama hatası: {str(e)}"
            self.error_logs.append(err)
            print(err)
        return games

    def scan_epic_games(self):
        games = []
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Epic Games\EpicGamesLauncher")
            epic_path = winreg.QueryValueEx(key, "AppDataPath")[0].strip('"')
            manifest_path = os.path.join(epic_path, "Manifests")
            if os.path.exists(manifest_path):
                for file in os.listdir(manifest_path):
                    if file.endswith('.item'):
                        with open(os.path.join(manifest_path, file), 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            game_path = data.get('InstallLocation')
                            if game_path:
                                game_path = game_path.strip('"')
                                exe = self.find_exe(game_path)
                                if exe:
                                    game = {'name': data.get('DisplayName', 'Bilinmiyor'), 'path': exe}
                                    game['image'] = self.find_game_image(exe) or ""
                                    games.append(game)
        except Exception as e:
            err = f"Epic Games tarama hatası: {str(e)}"
            self.error_logs.append(err)
            print(err)
        return games

    def scan_gog(self):
        games = []
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\GalaxyClient\paths")
            gog_client = winreg.QueryValueEx(key, "client")[0].strip('"')
            games_path = os.path.join(os.path.dirname(gog_client), "Games")
            if os.path.exists(games_path):
                for folder in os.listdir(games_path):
                    game_path = os.path.join(games_path, folder)
                    exe = self.find_exe(game_path)
                    if exe:
                        game = {'name': folder, 'path': exe}
                        game['image'] = self.find_game_image(exe) or ""
                        games.append(game)
        except Exception as e:
            err = f"GOG Galaxy tarama hatası: {str(e)}"
            self.error_logs.append(err)
            print(err)
        return games

    def scan_xbox_games(self):
        games = []
        try:
            output = subprocess.check_output(
                ["powershell", "-Command", "Get-StartApps | ConvertTo-Json"],
                universal_newlines=True,
                encoding="utf-8",
                errors="replace"
            )
            apps = json.loads(output)
            # apps, bir sözlük ya da liste olabilir; listeye dönüştürelim:
            if isinstance(apps, dict):
                apps = [apps]
            # Oyunları tanımlamak için örnek anahtar kelime listesi:
            game_keywords = [
                "halo", "forza", "minecraft", "gears", "sea of thieves", 
                "destiny", "witcher", "assassin", "battlefield", "cod", "persona", "no man's sky"
            ]
            for app in apps:
                name = app.get("Name", "")
                appid = app.get("AppID", "")
                # Eğer isim, belirlenen anahtar kelimelerden herhangi birini içeriyorsa oyuna ekleyelim:
                if any(keyword in name.lower() for keyword in game_keywords):
                    unique = self.generate_unique_key("Xbox", appid, set(g.get('unique', '') for g in self.games))
                    game = {
                        "name": name,
                        "launcher": "Xbox",
                        "path": "explorer.exe",  # UWP oyunları explorer.exe ile başlatılır.
                        "args": f"shell:AppsFolder\\{appid}",  # Bu argüman ilgili uygulamayı başlatır.
                        "image": "",
                        "source": "scanned",
                        "unique": unique
                    }
                    games.append(game)
        except Exception as e:
            err = f"Xbox oyunları tarama hatası: {str(e)}"
            self.error_logs.append(err)
            print(err)
        return games

    def scan_ubisoft(self):
        games = []
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Ubisoft\Launcher")
            ubisoft_path = winreg.QueryValueEx(key, "InstallDir")[0].strip('"')
            games_path = os.path.join(ubisoft_path, "games")
            if os.path.exists(games_path):
                for folder in os.listdir(games_path):
                    game_path = os.path.join(games_path, folder)
                    exe = self.find_exe(game_path)
                    if exe:
                        game = {'name': folder, 'path': exe}
                        game['image'] = self.find_game_image(exe) or ""
                        games.append(game)
        except Exception as e:
            err = f"Ubisoft Connect tarama hatası: {str(e)}"
            self.error_logs.append(err)
            print(err)
        return games

    def scan_origin(self):
        games = []
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Origin")
            origin_client = winreg.QueryValueEx(key, "ClientPath")[0].strip('"')
            local_content = r"C:\ProgramData\Origin\LocalContent"
            if os.path.exists(local_content):
                for folder in os.listdir(local_content):
                    game_path = os.path.join(local_content, folder)
                    exe = self.find_exe(game_path)
                    if exe:
                        game = {'name': folder, 'path': exe}
                        game['image'] = self.find_game_image(exe) or ""
                        games.append(game)
        except Exception as e:
            err = f"Origin tarama hatası: {str(e)}"
            self.error_logs.append(err)
            print(err)
        return games

    def find_exe(self, folder):
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.endswith('.exe') and not file.lower().startswith('unins'):
                    return os.path.join(root, file).strip('"')
        return None

    def find_game_image(self, exe_path):
        directory = os.path.dirname(exe_path)
        for filename in ["icon.png", "logo.png", "cover.png"]:
            image_path = os.path.join(directory, filename)
            if os.path.exists(image_path):
                return image_path
        return None

    def get_steam_client_path(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")
            steam_path = winreg.QueryValueEx(key, "InstallPath")[0].strip('"')
            client_exe = os.path.join(steam_path, "steam.exe")
            if os.path.exists(client_exe):
                return client_exe
        except Exception as e:
            print(f"Steam client yolu alınamadı: {str(e)}")
        return None

    def get_epic_client_path(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Epic Games\EpicGamesLauncher")
            appdata_path = winreg.QueryValueEx(key, "AppDataPath")[0].strip('"')
            potential_path = os.path.join(os.path.dirname(appdata_path), "Portal", "Binaries", "Win32", "EpicGamesLauncher.exe")
            if os.path.exists(potential_path):
                return potential_path
        except Exception as e:
            print(f"Epic Games client yolu alınamadı: {str(e)}")
        return None

    def get_gog_client_path(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\GalaxyClient\paths")
            gog_client = winreg.QueryValueEx(key, "client")[0].strip('"')
            if os.path.exists(gog_client):
                return gog_client
        except Exception as e:
            print(f"GOG Galaxy client yolu alınamadı: {str(e)}")
        return None

    def get_ubisoft_client_path(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Ubisoft\Launcher")
            ubisoft_path = winreg.QueryValueEx(key, "InstallDir")[0].strip('"')
            client_exe = os.path.join(ubisoft_path, "UbisoftConnect.exe")
            if os.path.exists(client_exe):
                return client_exe
        except Exception as e:
            print(f"Ubisoft Connect client yolu alınamadı: {str(e)}")
        return None

    def get_origin_client_path(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Origin")
            origin_client = winreg.QueryValueEx(key, "ClientPath")[0].strip('"')
            if os.path.exists(origin_client):
                return origin_client
        except Exception as e:
            print(f"Origin client yolu alınamadı: {str(e)}")
        return None

    def is_process_running(self, process_name):
        try:
            tasks = subprocess.check_output("tasklist", shell=True).decode()
            return process_name.lower() in tasks.lower()
        except Exception as e:
            print(f"Process kontrol hatası: {str(e)}")
            return False


#########################################
# Programın Başlatılması
#########################################
import ctypes
import sys

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if __name__ == "__main__":
    try:
        if not is_admin():
            # ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
            app = GameLauncher()
            app.root.mainloop()
        else:
            app = GameLauncher()
            app.root.mainloop()
    except Exception as e:
        print("Hata oluştu:", e)
        input("Çıkmak için bir tuşa basın...")
