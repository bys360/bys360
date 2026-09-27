# BYS360 Performans Tamamlama Faz 4 — 3. Amir Opsiyonelliği ve Akış Temizliği

Bu overlay, Faz 4 kapanış kriterlerini tek karar merkezine bağlar.

## Kapsam

- 3. amir zorunlu değildir.
- 3. amir yoksa boş sütun, sahte görev ve yanlış bekleme statüsü üretilmez.
- 3. amir yorum modundaysa puan beklenmez; kullanıcıya “3. Amir Görüş/Yorum Bekliyor” dili gösterilir.
- 3. amir puan modundaysa ağırlık hesabına dahil olabilir.
- Amir ağırlıkları her durumda toplam %100 olacak şekilde normalize edilir.
- Eski `third_supervisor_policy.py` ve `third_supervisor_column_visibility.py` çağrıları yeni merkez servise bağlanır.

## Uygulama

```powershell
cd C:\bys360\project
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\BYS360_PERFORMANCE_COMPLETION_PHASE4_THIRD_MANAGER_CENTER_V1_OVERLAY.zip" -DestinationPath "C:\bys360\project" -Force
powershell -ExecutionPolicy Bypass -File .\scripts\windows\repair_bys360_performance_completion_phase4_third_manager_center.ps1 -ProjectRoot "C:\bys360\project" -Mode all
```

Başarılı sonuç:

```text
BYS360_PERFORMANCE_COMPLETION_PHASE4_THIRD_MANAGER_CENTER_APPLY_OK
```

## Kapanış Kontrolü

```powershell
python .\scripts\performance\check_bys360_performance_completion_phase4_third_manager_center.py --project-root "C:\bys360\project" --app-check
```

