# BYS360 Mobile Contract Regression Recovery V1

Amaç: güvenlik/import temizliği sonrası kırılan mobil API contract testlerini, yeni özellik eklemeden geri toparlamak.

Düzeltmeler:
- `app/api/mobile/routes.py` tekrar ince facade yapılır (`<=300` satır).
- `routes.py` içinde route decorator bırakılmaz.
- Domain dosyalarındaki 24 mobil contract endpoint korunur.
- Eski exec tabanlı düşük riskli okuma köprüleri kontrollü registry ile kayıt edilmeye devam eder.
- `personnel_service.py` artık personel create helperlarını domain modülünden alır; `routes.py` içinde olmayan helpera bakmaz.

Komutlar:

```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_MOBILE_CONTRACT_REGRESSION_RECOVERY_V1_OVERLAY_FLAT.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_mobile_contract_regression_recovery_v1.ps1 -ProjectRoot "C:\bys360\project" -Mode audit
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_mobile_contract_regression_recovery_v1.ps1 -ProjectRoot "C:\bys360\project" -Mode fix-safe -RunCompile
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_mobile_contract_regression_recovery_v1.ps1 -ProjectRoot "C:\bys360\project" -Mode verify -RunCompile
```

Beklenen statü: `OK`.
