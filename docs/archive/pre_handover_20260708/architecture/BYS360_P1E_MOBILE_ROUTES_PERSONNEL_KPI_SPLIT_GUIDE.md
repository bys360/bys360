# BYS360 P1E Mobile Routes Personnel/KPI Split

Bu paket P1D sonrası mobil API `routes.py` içinde kalan personel tüm liste/ekleme ve KPI hedef yönetimi endpoint bloklarını domain dosyalarına ayırır.

Beklenen kazanım:

- URL/endpoint sözleşmesi korunur.
- Route sayısı değişmez.
- `routes.py` ince facade seviyesine yaklaşır.
- App factory smoke ve secret gate temiz kalır.

Çalıştırma:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_claude_score_uplift_p1e_mobile_routes_personnel_kpi_split.ps1 -ProjectRoot "C:\bys360\project" -Mode all -CompileAll -RunAppFactorySmoke -RunSecretGate
```
