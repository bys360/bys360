# 04 — BYS360 Rol ve Yetki Mimarisi

| Alan | Değer |
|---|---|
| Kaynak (incelenen) | `origin/assistant-v2-full` @ `f796107fa6ab42096065a02d4724ec7e8d22f608` |
| Belgelenmiş production SHA | `cdae27953adcbdd8270fe78dcd52351725d3aecd` (`SOURCE_OF_TRUTH.md:12`) |
| Hazırlanma tarihi | 2026-10-11 |

Bu belge yetki kararlarının **kodda** nasıl verildiğini anlatır. Satır numaraları dal ucuna aittir. Dal ucunda olup production SHA'da bulunmayan kurallar §9'da ayrıca listelenmiştir. Hiçbir bulgu bu çalışma kapsamında düzeltilmemiştir.

---

## 1. Rol veri modeli

- Kullanıcı başına **tek rol**: `User.role = db.Column(db.String(50), nullable=False, default="personel")` (`app/models/core_models.py:59`). FK veya enum değildir; serbest metindir.
- Ayrıca görüntü alanları vardır: `role_label` (`core_models.py:60`), `unvan` (`core_models.py:58`). Amir zinciri alanları: `yonetici_sicil`, `ikinci_yonetici_sicil`, `ucuncu_yonetici_sicil` (`core_models.py:73-75`), birim alanları `birim`, `ust_birim` (`core_models.py:71-72`).
- Yönetim formunda seçilebilen roller `ROLE_CHOICES` (`app/admin/routes.py:81-90`): `admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`, `mali_musavir`, `birim_sorumlusu`, `koordinator`, `personel`.
- Görüntü sözlüğü `ROLE_DISPLAY_LABELS` bunlara ek olarak `hukuk_musaviri`'yi içerir (`app/services/role_display.py:22-31`); README bunu "kapalı rol sözlüğü" olarak anar (`README.md:56-63`).
- Rol karşılaştırması `strip().lower()` ile normalize edilir (`app/route_support.py:112-113`).

Gözlem: Kodun farklı yerlerinde `ROLE_CHOICES` dışında rol anahtarları tanımlıdır — ör. `sistem_yoneticisi`, `system_admin`, `super_admin`, `yonetici`, `ik`, `personel_yonetimi`, `performans_yetkilisi`, `dosya_merkezi_yetkilisi` (`app/services/performance/completion_phase3_visibility_scope.py:35-80`, `app/file_center/permissions.py:119-129`, `app/services/settings/effective_menu_parts/block_context.py:7`). Bu anahtarların hangi süreçle kullanıcılara atandığı (form dışında, ör. Excel içe aktarma veya doğrudan DB) bu belgede doğrulanmadı.

## 2. Rol aileleri ve dekoratörler

`app/route_support.py:66-70`:

| Küme | İçerik |
|---|---|
| `ADMIN_FAMILY_ROLES` | `admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`, `mali_musavir` |
| `MANAGER_FAMILY_ROLES` | admin ailesi + `birim_sorumlusu`, `koordinator` |
| `PORTAL_EDITOR_ROLES` | admin ailesi + `koordinator` |
| `PORTAL_GROUP_MANAGER_ROLES` | admin ailesi |
| `PORTAL_PROFILE_ADMIN_ROLES` | `admin`, `baskan`, `baskan_yardimcisi` |

Dekoratörler:

- `admin_required`, `manager_required` = `_require_role_family(...)` (`app/route_support.py:443-459`). Oturum yoksa `/login`'e yönlendirir; rol ailede değilse `render_access_denied()` (403). **Menü matrisine bakmaz**; yalnız `current_user.role`'e bakar (`user_has_any_role`, `route_support.py:94-97`).
- `portal_editor_required` (`route_support.py:462-471`).
- `app/auth/decorators.py` yalnız bu dekoratörleri yeniden dışa aktaran uyumluluk katmanıdır.

Gözlem: `mali_musavir` admin ailesindedir; bu, `admin_required` korumalı tüm ekranlara (ör. `/settings` yazma) erişim anlamına gelir. 2026-09-02 belgesi bu rolün gerçek veri kapsamını "NOT_YET_FINALIZED" bırakmıştır (`docs/current_state/11_BYS360_Rol_Yetki_ve_Erisim_Kontrol_Modeli.md` §8).

## 3. Menü yetki matrisi

### 3.1 Tablolar

| Model | Tablo | Anahtar | Kaynak |
|---|---|---|---|
| `RoleMenuDefault` | `role_menu_defaults` | (`role_name`, `menu_key`) tekil | `app/models/settings_models.py:13-30` |
| `UnitMenuProfile` | `unit_menu_profiles` | (`unit_name`, `menu_key`) tekil | `app/models/settings_models.py:70-87` |
| `UserMenuPermission` | `user_menu_permissions` | (`user_id`, `menu_key`) tekil; `source_type` varsayılan `user_override` | `app/models/core_models.py:386-405` |
| `SettingsChangeLog` | `settings_change_logs` | Yetki değişikliklerinin denetim izi ve geri alma zinciri | `app/models/settings_models.py:89+` |

### 3.2 Çözümleme sırası

Kod içi kayıt: "Rol matrisi tabanı → birim profili → kişi özel ayarı → teknik/rol güvenlik kapısı" (`app/services/settings/effective_menu.py:132-136`). Zincir:

```
app/route_support.py:404 build_menu_visibility_map(user)        (ince köprü)
  → app/services/settings/effective_menu.py                      (facade, 299 satır)
    → app/services/settings/effective_menu_parts/*.py            (rol/birim/kişi/çekirdek politika blokları)
app/route_support.py:525 build_menu_visibility_map (yeniden tanım) → kaldırılmış modül anahtarlarını süzer
```

"Teknik/rol güvenlik kapısı" katmanında bazı anahtarlar için izinli rol kümeleri sabit kodludur; örneğin `support_all` yalnız `admin`, `baskan`, `baskan_yardimcisi`, `grup_baskani`, `mali_musavir`, `koordinator`, `birim_sorumlusu` için (`app/services/settings/effective_menu_parts/bys360_constants.py:43,121`).

### 3.3 `menu_key_required`

`app/route_support.py:424-440`: oturum yoksa `/login`; `can_access_menu(current_user, key)` False ise 403. Kod yorumu admin/üst rol bypass'ının kaldırıldığını belirtir (`route_support.py:430-433`). Menü görünürlüğü ve route kararı aynı `build_menu_visibility_map` çıktısına dayanır; bu nedenle `menu_key_required` korumalı bir route için "menüde gizli ama route açık" durumu yapısal olarak oluşmaz (DOC-11 §4). Bu garanti yalnız dekoratörü taşıyan route'lar için geçerlidir; tüm route'ların hangi dekoratörü taşıdığına dair tam bir envanter bu belgede çıkarılmadı (bkz. `reports/quality/BYS360_AUTHORIZATION_MATRIX_V1.json`, üretim tarihi bu belgede doğrulanmadı).

Bilinen dar istisna: 3 performans-dönem menü anahtarı için admin ailesine görünürlük zorlanır (DOC-11 §4.4; `effective_menu_parts/public_build_context.py`, `bys360_context.py`). Satır numaraları dal ucunda yeniden doğrulanmadı.

### 3.4 Salt-okunur rol matrisi ekranı

`/admin/role-matrix` kod içi sabit veriyi (`app/services/role_matrix_ui_service.py`) gösterir, DB tablolarını okumaz; gerçek görünürlükten sapabilir (DOC-11 §7). Gerçek durum `/settings` matrisinden veya tablolardan okunmalıdır.

## 4. Açık (explicit) yetkiler

### 4.1 `personnel_read_all` — kurum geneli personel rehberi okuma (yalnız dal ucunda)

`app/services/personnel_read_grant.py:1-69`:

- Depolama: `user_menu_permissions` satırı, `menu_key="personnel_read_all"`, `is_visible=True`, `source_type="user_override"`; migration gerekmez (`:7-8`).
- Okuyucu `has_personnel_read_all_grant` rolü, `role_label`'ı, rol varsayılanlarını ve birim profillerini yok sayar; DB hatasında **kapalı** döner (`:45-69`).
- Atama: yalnız `admin` rolü, yalnız **başka** bir kullanıcı için, `/settings` kişi matrisinde (`form_action=save_user_visibility`) (`app/main_handlers/account_settings_helpers.py:120-130,757-768`). Kendi kendine atama reddedilir. Rol/birim profilleri bu anahtarı taşımaz (`personnel_read_grant.py:40-42`).
- Kullanım yeri: yalnız mobil personel listesi uçları (`app/api/mobile/routes.py:86-89`, `app/api/mobile/domains/personnel_read.py:23-26`). Web tarafı personel ekranlarında bu yetkinin kullanıldığına dair referans bulunamadı (`grep -rln personnel_read_all app`).
- **Production SHA'da bu dosya yoktur** (`git cat-file -e cdae2795:app/services/personnel_read_grant.py` → yok).

### 4.2 `support_all` — tüm destek talepleri

`app/services/support_ticket_access.py:7-45` (dal ucu):

- `can_view_all_support_tickets(user)` = `can_access_menu(user, "support_all")`; rol adı kısayolu yok (`:27-34`).
- Tekil talep: oluşturan veya atanan kişi her zaman görür; diğerleri için `support_all` **ve** özel talep kuralı (`:37-45`).
- Özel (`is_private`) talep: admin ailesi her zaman; diğerleri yalnız talebin birim anlık görüntüsü kendi `birim`/`ust_birim` değeriyle eşleşirse (`:10-24`).
- Web (`app/support/routes.py:263,277,283`) ve mobil (`app/api/mobile/shared.py:224,235`, `domains/dashboard.py:46`) aynı fonksiyonu kullanır.
- Production SHA'da dosya vardır fakat `can_view_all_support_tickets` / `can_view_support_ticket` fonksiyonları yoktur (PR #60 ile eklendi).

## 5. Dosya Merkezi yetkileri

`app/file_center/permissions.py` — merkezi menü matrisinden **ayrı** bir model:

- Kendi tablosu `FileCenterRolePermission`; 15 izin bayrağı (`PERMISSION_FIELDS`, `:21-37`) ve kod içi varsayılan rol matrisi (`:48-117`).
- Rol kimliği yalnız saklanan alanlardan: `_ROLE_IDENTITY_ATTRS = ("role", "role_key", "role_name")` (`:177`).
- Etkin rol önceliği: `admin`, `sistem_yoneticisi`, `dosya_merkezi_yetkilisi`, `yonetici`, `personel`; sonra "yönetici benzeri" ve "admin benzeri" ipuçları (`:214-225`, ipucu kümeleri `:119-129`).
- `_permission`: önce DB matrisi; DB satırı yoksa veya tablo hazır değilse, admin ipucu varsa **izin verir**, yoksa kod içi varsayılan (`:254-266`). `can_use_file_center` varsayılanı `True` (`:391-392`).
- Başkasının dosyasını okuma/silme/paylaşma: yalnız saklanan rolü tam `admin` olan ve Dosya Merkezi admin iznine sahip kullanıcı (`:365-381`).
- Rate limit: misafir indirme/yükleme ve parça yükleme uçlarına ayrı limitler (`app/security/api_rate_limit.py:22-31`).

Gözlem (kodda var): Matris tablosu okunamadığında (`SQLAlchemyError`) karar kod içi varsayılanlara düşer (`:228-252`); bu "fail-closed" değil "varsayılana dön" davranışıdır.

## 6. Performans değerlendirme zincirleri

- Amir zinciri `users.yonetici_sicil` / `ikinci_yonetici_sicil` / `ucuncu_yonetici_sicil` alanlarındaki **sicil numarası** ile kurulur (`core_models.py:73-75`; Excel başlık eşlemesi `app/services/performance/canonical_chain_service.py:9-17`).
- Geri bildirim görüşmeleri (dal ucu, PR #57): görüşmeyi yalnız tarafları (çalışan ve görüşme amiri) görür; hiçbir rol, `admin` dahil, bunu genişletmez. Talep, talepte adı geçen `level_1/2/3_manager_id` amirlerine görünür. Görüşme oluşturma, rol + görev ilişkisi (talepte adı geçen amir veya hiyerarşi amiri) gerektirir (`app/services/performance/feedback_meeting_access.py:1-21,53-119`).
- Faz 3 görünürlük merkezi: `ADMIN_ROLES={"admin","super_admin"}` kurum geneli; `SCOPED_MANAGER_ROLES` (`system_admin`, `sistem_yoneticisi`, `yonetici`) hiyerarşi kapsamına düşürüldü (`app/services/performance/completion_phase3_visibility_scope.py:35-55`; dosya docstring'i `:8-17`).
- Hukuk Müşavirliği için tek amirli özel kural, `unvan` ve `birim` metinlerine göre (`app/services/performance/common.py:148-175`).

## 7. Mobil API yetki modeli

- Kimlik: Bearer token → `require_mobile_user` (`app/api/mobile/shared.py:600-607`).
- Kurum geneli kapsam: `_GLOBAL_ROLES = {admin, başkan, baskan, baskanlik, başkan_yardımcısı, baskan_yardimcisi}` (`shared.py:80-87`); yalnız saklanan `role` okunur, `role_label` okunmaz (`shared.py:95-110`).
- Teknik roller (`sistem_yoneticisi`, `system_admin`) yalnız teknik, kişisel olmayan özetler alır (`shared.py:99-100`).
- Web `ADMIN_FAMILY_ROLES` ile mobil `_GLOBAL_ROLES` farklı kümelerdir (`grup_baskani`, `mali_musavir` mobilde global değil). 2026-09-30 inceleme bunu "insan kararı gerektiren" konu olarak listeler (`docs/technical-review/BYS360_TEKNIK_INCELEME_2026-09-30.md:168`).

## 8. Gözlenen zayıflıklar (olgusal; düzeltilmedi)

1. **Unvan/metin tabanlı sınıflandırma.** `is_system_user` bir kullanıcıyı `role_label`, `unvan` ("sistem yoneticisi"), e-posta öneki (`admin@`, `system@`, `sysadmin@`), sicil (`admin`, `system`) veya birim adına göre "sistem kullanıcısı" sayar (`app/services/hierarchy_rulebook_service.py:99-119`). Bu sonuç performans kapsamından çıkarmada kullanılır (`app/services/performance/common.py:123-136`, `app/services/performance/hierarchy.py:146-148`). `is_president` `unvan == "baskan"` veya `role_label` ile de doğru döner (`common.py:139-145`; `hierarchy_rulebook_service.py:122-125`). Bu fonksiyonlar doğrudan erişim izni vermez; zincir ve kapsam hesaplamasını etkiler.
2. **Rol fallback'i.** `hierarchy_rulebook_service._role` `role` boşsa `role_label`, o da boşsa `unvan` kullanır (`:77-79`); `role` NOT NULL ve varsayılanlı olduğundan pratik etkisi sınırlıdır.
3. **Dağınık rol kümeleri.** Aynı kavram için birden çok sabit küme vardır: `route_support.ADMIN_FAMILY_ROLES`, `app/services/ui_context/scope.py:7`, `app/services/cic/access_policy.py:6`, `completion_phase3_visibility_scope.ADMIN_ROLES`, `app/services/menu_visibility.py:121`, `app/services/role_matrix_ui_service.py:61-64`, mobil `_GLOBAL_ROLES`. Tutarlılık testle korunuyor olabilir; bu belgede doğrulanmadı.
4. **Serbest metin rol alanı.** `User.role` enum/FK değil; `ROLE_CHOICES` dışındaki değerler (ör. `yonetici`, `ik`) kod tarafından tanınır (§1).
5. **Dosya Merkezi varsayılana dönüşü** (§5) ve `can_use` varsayılanı `True`.
6. **Bakım modu bypass rolleri** admin ailesinden farklıdır (`mali_musavir` hariç, `koordinator` dahil) — `docs/handover/BYS360_FEATURE_COVERAGE_MATRIX.md` #34 (tarihsel; dal ucunda yeniden doğrulanmadı).
7. **Mobil login** hesap bazlı kilit içermez; yalnız global IP limiti (`app/api/mobile/services/auth_service.py:30-56`).
8. **Denetim izi kapsamı.** Yetki matrisi değişiklikleri `settings_change_logs`'a yazılır; giriş denemeleri için ayrı audit kaydı kanıtı 2026-09-02'de bulunamamıştı (DOC-12 §3.1).

## 9. Production SHA ile dal ucu arasındaki yetki farkları

Production SHA'daki kod (`git show cdae2795:<dosya>`) ile karşılaştırma:

| Konu | Production (`cdae2795`) | Dal ucu (`f796107f`) | PR |
|---|---|---|---|
| Mobil global roller | `_GLOBAL_ROLES` ayrıca `sistem_yoneticisi`, `system_admin`, `personel_yonetimi`, `ik`, `performans_yetkilisi` içerir (`app/api/mobile/shared.py:74-86`) | Bu 5 rol çıkarıldı | #59 |
| Mobil rol okuma | `_role_key` `role` boşsa `role_label`'a düşer (`shared.py:94-95`) | Yalnız `role` | #59 |
| Personel rehberi kurum geneli | Rol adına bağlı | Açık `personnel_read_all` yetkisi | #59 |
| Faz 3 performans görünürlüğü | `ADMIN_ROLES` `system_admin`, `sistem_yoneticisi`, `yonetici` içerir (`completion_phase3_visibility_scope.py:35-43`) | Bunlar kapsamlı yöneticiye düşürüldü | #67 |
| Dosya Merkezi rol kimliği | `_ROLE_IDENTITY_ATTRS` `role_label`, `title`, `position`, `job_title` içerir (`app/file_center/permissions.py:171`) → **görüntü/unvan alanı yetki verebilir** | Yalnız saklanan rol alanları | #62 |
| Başkasının dosyası | Ayrı `can_read_other_users_files` fonksiyonu yok; karar `is_file_center_admin` (`permissions.py:348`) üzerinden verildiği değerlendirilir (route düzeyinde doğrulanmadı) | Ayrıca saklanan rol tam `admin` | #62 |
| Destek tüm talepler | Rol/menü karışık kural | Tek `support_all` kuralı (web+mobil) | #60 |
| Geri bildirim görüşmeleri | Rol bazlı görünürlük | Yalnız taraflar + görev ilişkisi | #57 |
| KPI hedefleri kurum geneli | — | Yalnız tam saklanan global rol | #64 |
| Dönem içi notlar | Teknik roller kurum geneli | Teknik roller kurum geneli değil | #63 |

**Sonuç:** Canlı sistem production SHA'yı çalıştırdığı sürece (`SOURCE_OF_TRUTH.md:12,20`), yukarıdaki daha geniş yetki kuralları canlıda geçerlidir; dal ucundaki daraltmalar cutover yapılana kadar etkili değildir. Bu, bu belgenin en önemli yetki bulgusudur.

## 10. Yetki kararının akışı (özet)

1. Web isteği: Flask-Login oturumu + `security_stamp` eşleşmesi (`app/__init__.py:45-58`).
2. Route dekoratörü: `admin_required` / `manager_required` (rol ailesi) ve/veya `menu_key_required` (menü haritası).
3. Servis/sorgu kapsamı: modül servisleri (ör. Faz 3 görünürlük merkezi, `feedback_meeting_access`, `support_ticket_access`, Dosya Merkezi `permissions`) satır düzeyinde kapsam uygular.
4. Mobil istek: Bearer token → `require_mobile_user` → mobil domain modülündeki rol/kapsam kontrolü.
