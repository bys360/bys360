from __future__ import annotations

import os

from app import create_app

GB = 1024 * 1024 * 1024

app = create_app()

# BYS360 Dosya Merkezi - local büyük dosya testi
file_center_max_bytes = int(float(os.getenv("FILE_CENTER_MAX_FILE_GB", "5")) * GB)

# Dosya yükleme uçlarının istek limiti (#105); diğer istekler config.py'deki küçük limitlerde kalır.
app.config["UPLOAD_MAX_CONTENT_LENGTH"] = file_center_max_bytes

# Multipart/form parser tarafında 203 MB gibi dosyaların CSRF/form okumasında takılmaması için local testte yükseltilir.
# Bu ayar canlıya öneri değildir; sadece local büyük dosya geliştirme içindir.
app.config["MAX_FORM_MEMORY_SIZE"] = file_center_max_bytes

application = app
