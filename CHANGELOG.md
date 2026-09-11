# Changelog / Änderungsprotokoll

**Deutsch** | [English](#english) | [Русский](#русский) | [Français](#français) | [中文](#中文)

---

## Deutsch

### 1.9.1 – Installer v18 (11.09.2026)
- Tiefenprüfung der Felderkennung: Tabellen-Zellen werden vor den
  Zeilen-Paaren erkannt (keine Phantom-Felder mehr auf Gitterlinien)
- Saubere Raster-Beschriftungen: mehrzeilige Zeilen-Phrase + Spalten-
  header in Klammern; Wochentags-Spalten (Mo–So) werden Checkboxen
- Beschriftungen enden am letzten Doppelpunkt („Datum: Georgsmarienhütte“
  → „Datum“); Label-Phrasen über, unter und neben Feldern
- Eingabebänder müssen leer sein (keine Phantom-Bänder über
  Spalten-Headern)
- Öffentliches Repository mit Dokumentation in fünf Sprachen

### 1.9.0 – Installer v17 (10.09.2026)
- **Zeilen-Paar-Modell**: Eingabetext steht genau AUF der Eingabelinie
  (wie handschriftlich), nicht auf der Beschriftung
- Werkzeug „Feld verschieben“: erkannte Felder mit der Maus
  neu positionieren
- 45 Werkzeug-Symbole (lokal gezeichnet), Hover-Erklärungen
- Helles/dunkles Design mit Umschalter, Auswahl wird gespeichert
- OCR-Vorverarbeitung (Graustufen, 2×, Auto-Kontrast)

### 1.8.0 – Installer v16 (10.09.2026)
- Felderkennung für echte Formulare überarbeitet: Typ-Fallen behoben
  („Bisherige Schule“ = Text, nicht Datum), keine Scheinfelder mehr aus
  Seitenrahmen/Zierlinien, getrennte Checkbox-Optionen („Mutter“/
  „Vater“), Unterschriftslinien mit Label darunter, Vier-Feld-Zeilen
  vollständig

### 1.7.1 – Installer v15 (10.09.2026)
- Installation läuft trotz Windows-Blockierung einzelner Bibliotheken
  durch (Degradation mit klarer Meldung statt Abbruch)
- Mehrpunkt-Formen (Polygon, verbundene Linien, Kommentarwolke,
  Textlegende), Konvertieren, Dokumenteigenschaften, zertifizierte Kopie
- Alte Installationen und Verknüpfungen werden automatisch aufgeräumt

### 1.7.0 – Installer v14 (09.09.2026)
- Acrobat-Werkzeugkatalog vollständig (Auswählen bis Stempel)

### Frühere Versionen
- Kernfunktionen: Analyse, Formularerkennung und -füllung, OCR,
  Datentresor (AES-256-GCM), Versionsvergleich, Export
  (Word/Excel/PowerPoint/Text/RTF), Signieren, Schwärzen, Drucken

---

## English

### 1.9.1 – Installer v18 (2026-09-11)
- Deep audit of field detection: table cells are detected before line
  pairs (no more phantom fields on grid lines)
- Clean grid captions: multi-line row phrase + column header in
  brackets; weekday columns (Mon–Sun) become checkboxes
- Captions end at the last colon (“Datum: Georgsmarienhütte” →
  “Datum”); label phrases above, below and beside fields
- Input bands must be empty (no phantom bands over column headers)
- Public repository with documentation in five languages

### 1.9.0 – Installer v17 (2026-09-10)
- **Line-pair model**: the text you type sits exactly ON the input line
  (like handwriting), not on the caption
- “Move field” tool: reposition detected fields with the mouse
- 45 tool icons (drawn locally), hover explanations
- Light/dark theme with toggle; the choice is remembered
- OCR pre-processing (greyscale, 2×, auto-contrast)

### 1.8.0 – Installer v16 (2026-09-10)
- Field detection reworked for real forms: type traps fixed (“Bisherige
  Schule” = text, not date), no more phantom fields from page frames and
  decorative lines, separate checkbox options, signature lines labelled
  below, four-field rows detected completely

### 1.7.1 – Installer v15 (2026-09-10)
- Installation proceeds even when Windows blocks individual libraries
  (clean degradation with a clear message instead of aborting)
- Multipoint shapes (polygon, connected lines, callout cloud, text
  callout), converting, document properties, certified copy
- Old installations and shortcuts are cleaned up automatically

### 1.7.0 – Installer v14 (2026-09-09)
- Complete Acrobat tool catalogue (from Select to Stamp)

### Earlier versions
- Core features: analysis, form detection and filling, OCR, data vault
  (AES-256-GCM), version comparison, export (Word/Excel/PowerPoint/
  text/RTF), signing, redaction, printing

---

## Русский

### 1.9.1 — Установщик v18 (11.09.2026)
- Глубокая проверка распознавания полей: ячейки таблиц распознаются
  раньше пар строк (фантомных полей на линиях сетки больше нет)
- Понятные подписи в сетках: многострочная фраза строки + заголовок
  столбца в скобках; столбцы дней недели (пн–вс) становятся флажками
- Подписи обрезаются по последнему двоеточию («Datum: Georgsmarienhütte»
  → «Datum»); фразы-подписи над, под и рядом с полями
- Полосы ввода должны быть пустыми (нет фантомных полос над
  заголовками столбцов)
- Публичный репозиторий с документацией на пяти языках

### 1.9.0 — Установщик v17 (10.09.2026)
- **Модель «пара строк»**: вводимый текст находится точно НА линии
  ввода (как от руки), а не на подписи
- Инструмент «Переместить поле»: перетаскивание распознанных полей мышью
- 45 значков инструментов (нарисованы локально), пояснения при наведении
- Светлая/тёмная темы с переключателем; выбор сохраняется
- Предобработка OCR (оттенки серого, 2×, автоконтраст)

### 1.8.0 — Установщик v16 (10.09.2026)
- Переработка распознавания полей для реальных форм: исправлены ловушки
  типов («Bisherige Schule» = текст, а не дата), устранены фантомные
  поля из рамок страницы и декоративных линий, разделены варианты
  флажков, подписи линий подписи снизу, полная поддержка строк из
  четырёх полей

### 1.7.1 — Установщик v15 (10.09.2026)
- Установка завершается, даже если Windows блокирует отдельные
  библиотеки (корректная деградация с понятным сообщением вместо
  прерывания)
- Многоугольные формы (полигон, соединённые линии, облачко, выноска),
  конвертация, свойства документа, заверенная копия
- Старые установки и ярлыки очищаются автоматически

### 1.7.0 — Установщик v14 (09.09.2026)
- Полный каталог инструментов Acrobat (от «Выделение» до «Штамп»)

### Более ранние версии
- Основные функции: анализ, распознавание и заполнение форм, OCR,
  хранилище данных (AES-256-GCM), сравнение версий, экспорт
  (Word/Excel/PowerPoint/текст/RTF), подписание, замазывание, печать

---

## Français

### 1.9.1 – Installateur v18 (11/09/2026)
- Audit approfondi de la détection des champs : les cellules de
  tableaux sont détectées avant les paires de lignes (plus de champs
  fantômes sur les lignes de grille)
- Légendes de grille propres : phrase de ligne multi-lignes + en-tête
  de colonne entre parenthèses ; les colonnes de jours de la semaine
  (lun–dim) deviennent des cases à cocher
- Les légendes s'arrêtent au dernier deux-points (« Datum :
  Georgsmarienhütte » → « Datum ») ; phrases de légende au-dessus,
  en dessous et à côté des champs
- Les bandes de saisie doivent être vides (plus de bandes fantômes sur
  les en-têtes de colonnes)
- Dépôt public avec documentation en cinq langues

### 1.9.0 – Installateur v17 (10/09/2026)
- **Modèle de paire de lignes** : le texte saisi se place exactement
  SUR la ligne de saisie (comme à la main), pas sur la légende
- Outil « Déplacer le champ » : repositionner les champs détectés à la
  souris
- 45 icônes d'outils (dessinées localement), explications au survol
- Thème clair/sombre avec bascule ; le choix est mémorisé
- Prétraitement OCR (niveaux de gris, ×2, contraste automatique)

### 1.8.0 – Installateur v16 (10/09/2026)
- Détection des champs repensée pour les formulaires réels : pièges de
  type corrigés (« Bisherige Schule » = texte, pas une date), plus de
  champs fantômes issus des cadres de page et lignes décoratives,
  options de cases à cocher séparées, légendes des lignes de signature
  en dessous, lignes à quatre champs détectées complètement

### 1.7.1 – Installateur v15 (10/09/2026)
- L'installation se poursuit même lorsque Windows bloque certaines
  bibliothèques (dégradation propre avec un message clair au lieu d'un
  arrêt)
- Formes multipoints (polygone, lignes reliées, bulle, légende),
  conversion, propriétés du document, copie certifiée
- Les anciennes installations et raccourcis sont nettoyés
  automatiquement

### 1.7.0 – Installateur v14 (09/09/2026)
- Catalogue d'outils Acrobat complet (de Sélection à Tampon)

### Versions antérieures
- Fonctions principales : analyse, détection et remplissage de
  formulaires, OCR, coffre-fort de données (AES-256-GCM), comparaison de
  versions, export (Word/Excel/PowerPoint/texte/RTF), signature,
  masquage, impression

---

## 中文

### 1.9.1 —— 安装程序 v18（2026-09-11）
- 字段识别深度检查：表格单元格先于行对识别（网格线上不再出现
  幽灵字段）
- 清晰的网格标签：多行行短语 + 括号中的列标题；星期列（周一至
  周日）成为复选框
- 标签在最后一个冒号处截断（„Datum: Georgsmarienhütte" →
  „Datum"）；字段上方、下方和旁边的标签短语
- 输入带必须为空（列标题上不再有幽灵输入带）
- 公开代码仓库，附带五种语言的文档

### 1.9.0 —— 安装程序 v17（2026-09-10）
- **行对模型**：输入的文字恰好落在输入线上（如同手写），
  而不是落在标签上
- “移动字段”工具：用鼠标重新定位识别出的字段
- 45 个工具图标（本地绘制），悬停说明
- 浅色/深色主题一键切换；自动记住选择
- OCR 预处理（灰度、2 倍放大、自动对比度）

### 1.8.0 —— 安装程序 v16（2026-09-10）
- 针对真实表单重新设计字段识别：修正类型陷阱（„Bisherige
  Schule" = 文本，而非日期），消除页面边框和装饰线产生的幽灵
  字段，分离复选框选项，签名线标签位于下方，完整识别四字段行

### 1.7.1 —— 安装程序 v15（2026-09-10）
- 即使 Windows 封锁个别库，安装也能完成（优雅降级并给出明确
  提示，而不是中断）
- 多点形状（多边形、折线、批注气泡、文本标注）、格式转换、
  文档属性、认证副本
- 自动清理旧安装和快捷方式

### 1.7.0 —— 安装程序 v14（2026-09-09）
- 完整的 Acrobat 工具目录（从“选择”到“图章”）

### 更早版本
- 核心功能：分析、表单识别与填写、OCR、数据保险库
  （AES-256-GCM）、版本对比、导出（Word/Excel/PowerPoint/文本/
  RTF）、签名、涂黑、打印
