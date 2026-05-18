```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Valartic — Your document has been analyzed</title>
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
              <p style="margin:0 0 16px;font-size:16px;line-height:1.55;color:#1c2b3a;">Hello,</p>
              <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:#3d4f63;">
                Thank you for placing your trust in <strong>Valartic</strong>. Your document has been processed by our analysis pipeline. Below is a <strong>summary</strong> of the main information we extracted.
              </p>
              <p style="margin:0 0 20px;font-size:15px;line-height:1.6;color:#3d4f63;">
                A detailed <strong>Excel workbook</strong> (structured extractions by worksheet) is <strong>attached to this email</strong> when the export is available.
              </p>
              <div style="background:#f6f8fb;border-radius:10px;padding:20px 22px;border-left:4px solid #c9a227;margin-bottom:22px;">
                <p style="margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:0.08em;color:#6b7c8f;">Task reference</p>
                <p style="margin:0;font-size:14px;font-weight:600;color:#0f2744;word-break:break-all;">{{TASK_ID}}</p>
                <p style="margin:16px 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:0.08em;color:#6b7c8f;">Document</p>
                <p style="margin:0;font-size:14px;font-weight:600;color:#0f2744;">{{DOCUMENT_NAME}}</p>
              </div>
              <p style="margin:0 0 12px;font-size:14px;font-weight:600;color:#0f2744;">Extraction summary</p>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:14px;color:#1c2b3a;">
                {{SUMMARY_ROWS}}
              </table>
              <p style="margin:24px 0 0;font-size:13px;line-height:1.55;color:#5a6b7d;">
                Questions? Reply to this email or contact your Valartic representative.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:20px 32px 28px;background:#f6f8fb;border-top:1px solid #dde4ec;">
              <p style="margin:0;font-size:12px;color:#7a8a9c;line-height:1.5;">
                © {{YEAR}} Valartic — Internal data; authorized use only.<br>
                This notification was generated automatically.
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
