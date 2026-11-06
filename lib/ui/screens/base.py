"""
base.py — ekranlar için ortak veri yükleme altyapısı.

Tasarım notu (gelecekteki web arayüzü):
    Ekranlar veriyi doğrudan dosyadan/subprocess'ten okumaz. Hepsi
    `self.provider` (DataProvider Protocol) üzerinden okur. Bu sayede
    Textual ekranları CLIProvider ile çalışırken, yarın bir WebProvider
    (REST/WebSocket) yazıldığında ekran kodu değişmeden aynı sözleşmeyi
    kullanabilir.

    Ağır iş (subprocess, dosya IO) her zaman worker thread'de yapılır;
    UI thread'i bloklanmaz.
"""
from __future__ import annotations

from textual import work
from textual.widget import Widget

from ..data import get_provider


class DataScreen(Widget):
    """Veri odaklı ekranların taban sınıfı.

    Alt sınıflar şunları uygular:
        fetch_data()  -> veriyi toplar (worker thread'de çalışır)
        apply_data(x) -> veriyi widget state'ine yazar
        compose()     -> state'ten UI üretir

    `refresh_interval` verilirse ekran kendini periyodik yeniler.
    """

    #: saniye cinsinden otomatik yenileme; None = kapalı
    refresh_interval: float | None = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._data = None
        self._loaded = False
        self._error: str | None = None

    # ── provider ──────────────────────────────────────────────
    @property
    def provider(self):
        """Aktif veri sağlayıcı (CLI, REST, mock...)."""
        return get_provider()

    # ── yaşam döngüsü ─────────────────────────────────────────
    def on_mount(self) -> None:
        self.reload()
        if self.refresh_interval:
            self.set_interval(self.refresh_interval, self._tick)

    def _tick(self) -> None:
        """Sadece görünür ekranı yenile (gizli sekmeler boşa IO yapmasın)."""
        try:
            if not self.is_on_screen:
                return
        except Exception:
            pass
        self.reload()

    @work(thread=True, exclusive=True, group="data")
    def reload(self) -> None:
        """Veriyi arka planda yeniden yükle ve ekranı tazele."""
        try:
            data = self.fetch_data()
        except Exception as exc:  # provider hatası UI'yı düşürmesin
            self.app.call_from_thread(self._on_error, exc)
            return
        self.app.call_from_thread(self._on_data, data)

    def _on_data(self, data) -> None:
        self._data = data
        self._loaded = True
        self._error = None
        self.apply_data(data)
        self.refresh(recompose=True)

    def _on_error(self, exc: Exception) -> None:
        self._error = str(exc)
        self._loaded = True
        self.refresh(recompose=True)

    # ── alt sınıfların uygulayacağı kancalar ──────────────────
    def fetch_data(self):
        raise NotImplementedError

    def apply_data(self, data) -> None:
        self._data = data

    # ── yardımcılar ───────────────────────────────────────────
    def loading_text(self) -> str:
        return "[dim]Loading…[/dim]"

    def error_text(self) -> str:
        return f"[red]Data error:[/red] [dim]{self._error}[/dim]"
