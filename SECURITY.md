# Security / Sicherheit / Безопасность / Sécurité / 安全

## Deutsch

**Alle Verarbeitung erfolgt lokal.** DocumentAI stellt keine
Netzverbindungen zu Servern her; es gibt keine Telemetrie mit
Dokumentinhalten und kein Cloud-Konto.

- **Datentresor**: AES-256-GCM, Schlüssel abgeleitet aus dem
  Master-Passwort (PBKDF2); das Passwort wird optional im Windows-Keyring
  gespeichert, niemals im Klartext
- **Geschützt speichern**: PDF-Verschlüsselung mit AES-256
- **Schwärzen**: entfernt Inhalt endgültig aus dem Dokument (kein
  Überdecken)
- **Signieren**: lokale Signaturen (pyhanko), selbstsignierte Zertifikate
  bleiben lokal
- Melden Sie Sicherheitslücken bitte über GitHub (privat:
  „Security“-Tab → „Report a vulnerability“)

## English

**All processing is local.** DocumentAI does not open network
connections to servers; there is no telemetry with document content and
no cloud account.

- **Data vault**: AES-256-GCM, key derived from the master password
  (PBKDF2); the password is optionally stored in the Windows keyring,
  never in plain text
- **Save protected**: PDF encryption with AES-256
- **Redaction**: removes content from the document permanently (not
  merely covering it)
- **Signing**: local signatures (pyhanko); self-signed certificates stay
  local
- Please report vulnerabilities via GitHub (privately: “Security” tab →
  “Report a vulnerability”)

## Русский

**Вся обработка выполняется локально.** DocumentAI не устанавливает
сетевых соединений с серверами; телеметрии с содержимым документов нет,
облачной учётной записи тоже.

- **Хранилище данных**: AES-256-GCM, ключ выводится из мастер-пароля
  (PBKDF2); пароль по желанию хранится в Windows Keyring, но никогда —
  в открытом виде
- **Защищённое сохранение**: шифрование PDF с AES-256
- **Замазывание**: окончательно удаляет содержимое из документа (а не
  просто закрашивает его)
- **Подписание**: локальные подписи (pyhanko); самоподписанные
  сертификаты остаются локальными
- Об уязвимостях сообщайте, пожалуйста, через GitHub (конфиденциально:
  вкладка «Security» → «Report a vulnerability»)

## Français

**Tout le traitement est local.** DocumentAI n'ouvre aucune connexion
réseau vers des serveurs ; il n'existe aucune télémétrie contenant le
contenu des documents et aucun compte cloud.

- **Coffre-fort de données** : AES-256-GCM, clé dérivée du mot de passe
  maître (PBKDF2) ; le mot de passe est stocké en option dans le
  trousseau Windows, jamais en clair
- **Enregistrement protégé** : chiffrement PDF en AES-256
- **Masquage** : supprime définitivement le contenu du document (et ne
  se contente pas de le couvrir)
- **Signature** : signatures locales (pyhanko) ; les certificats
  auto-signés restent locaux
- Signalez les vulnérabilités via GitHub (en privé : onglet
  « Security » → « Report a vulnerability »)

## 中文

**所有处理均在本地完成。** DocumentAI 不会与任何服务器建立网络
连接；不存在包含文档内容的遥测，也没有云账户。

- **数据保险库**：AES-256-GCM，密钥由主密码派生（PBKDF2）；
  密码可选择保存在 Windows 凭据管理器中，绝不以明文存储
- **受保护保存**：使用 AES-256 加密 PDF
- **涂黑（脱敏）**：将内容从文档中永久删除（而非仅仅覆盖）
- **签名**：本地签名（pyhanko）；自签名证书保留在本地
- 如发现安全漏洞，请通过 GitHub 私下报告（“Security”标签页 →
  “Report a vulnerability”）
