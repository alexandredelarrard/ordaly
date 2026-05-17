```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Valartic — Votre document a été analysé</title>
</head>
<body style="margin:0;padding:0;background-color:#e8ecf1;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#e8ecf1;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 8px 32px rgba(15,39,68,0.12);">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#0f2744 0%,#1a3a5c 100%);padding:28px 32px;text-align:left;">
              <div style="font-size:22px;font-weight:700;letter-spacing:0.04em;color:#ffffff;">VALARTIC</div>
              <div style="font-size:13px;color:#b8c5d6;margin-top:6px;">Commercial Real Estate Intelligence</div>
            </td>
          </tr>
          <!-- Accent bar -->
          <tr>
            <td style="height:4px;background:linear-gradient(90deg,#c9a227,#e8d48a);"></td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px;font-size:16px;line-height:1.55;color:#1c2b3a;">Bonjour,</p>
              <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:#3d4f63;">
                Nous avons terminé le traitement du fichier que vous avez transmis. Voici le <strong>résumé structuré</strong> produit par notre pipeline d’analyse (résultats de démonstration jusqu’au branchement du parseur agentique).
              </p>
              <div style="background:#f6f8fb;border-radius:10px;padding:20px 22px;border-left:4px solid #c9a227;margin-bottom:22px;">
                <p style="margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:0.08em;color:#6b7c8f;">Référence tâche</p>
                <p style="margin:0;font-size:14px;font-weight:600;color:#0f2744;word-break:break-all;">{{TASK_ID}}</p>
                <p style="margin:16px 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:0.08em;color:#6b7c8f;">Document</p>
                <p style="margin:0;font-size:14px;font-weight:600;color:#0f2744;">{{DOCUMENT_NAME}}</p>
              </div>
              <p style="margin:0 0 12px;font-size:14px;font-weight:600;color:#0f2744;">Extraction (mock)</p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:14px;color:#1c2b3a;">
                {{RESULTS_ROWS}}
              </table>
              <p style="margin:24px 0 0;font-size:13px;line-height:1.55;color:#5a6b7d;">
                Des questions ? Répondez directement à cet e-mail ou contactez votre interlocuteur Valartic.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:20px 32px 28px;background:#f6f8fb;border-top:1px solid #dde4ec;">
              <p style="margin:0;font-size:12px;color:#7a8a9c;line-height:1.5;">
                © {{YEAR}} Valartic — Données internes, usage réservé aux parties autorisées.<br>
                Cette notification a été générée automatiquement.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
```