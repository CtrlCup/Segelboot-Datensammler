"""WebDAV-Konfiguration (Template).

Diese Datei als `webdav_config.py` kopieren und Zugangsdaten eintragen.
`webdav_config.py` ist gitignored und wird NICHT nach GitHub gepusht.

Anbieter-Beispiele
──────────────────
pCloud (https://help.pcloud.com/article/webdav):
    EU-Region:  https://ewebdav.pcloud.com
    US-Region:  https://webdav.pcloud.com
    Login:      deine pCloud-E-Mail
    Passwort:   pCloud-Passwort — bei aktivem 2FA ein App-Passwort
                (pCloud → Settings → Security → App passwords)

Nextcloud / ownCloud:
    https://<server>/remote.php/dav/files/<USERNAME>
"""

WEBDAV = {
    "enabled": False,
    "hostname": "https://ewebdav.pcloud.com",
    "login": "dein-login@example.com",
    "password": "dein-passwort-oder-app-passwort",
    # Pfad auf dem Server, unter dem das Projekt liegt.
    # Wird bei Bedarf automatisch angelegt. Unterordner: data/, images/
    "remote_path": "/Segelboot-Datensammler",
    # Pull vor dem Scrapen / Push nach dem Scrapen ein-/ausschalten
    "pull_on_start": True,
    "push_on_end": True,
    # Nach erfolgreichem Push die lokalen Bild-Unterordner löschen
    # (spart Plattenplatz auf dem Server). DB bleibt lokal erhalten.
    "delete_images_after_push": False,
    # SSL-Verifizierung (False nur für self-signed Server)
    "verify_ssl": True,
    "timeout": 60,
}
