const nodemailer = require("nodemailer");

try {
  require("dotenv").config();
} catch (e) {}

async function sendPaymentEmail(to, name, plan, amount, link) {
  const host = process.env.SMTP_HOST || "smtp.gmail.com";
  const port = process.env.SMTP_PORT || 587;
  const user = process.env.SMTP_USER || process.env.DEMO_EMAIL || "";
  const pass = (process.env.SMTP_PASS || "").replace(/\s+/g, "");

  if (!pass) {
    console.log(`[Mailer] SMTP_PASS not set. Razorpay sends direct email to ${to}.`);
    console.log(`[Mailer Mock] Would send to: ${to} | ${name} | ${plan} | ₹${amount} | ${link}`);
    return { ok: true, note: "simulated" };
  }

  const transporter = nodemailer.createTransport({
    host,
    port: parseInt(port, 10),
    secure: port == 465,
    auth: { user, pass },
  });

  const info = await transporter.sendMail({
    from: `"PayEase Billing" <${user}>`,
    to: to,
    subject: `Complete your payment for ${plan} - PayEase`,
    html: `
      <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
        <h2 style="color: #0f172a; margin-top: 0;">PayEase Autopay Recovery</h2>
        <p>Hi <strong>${name}</strong>,</p>
        <p>As discussed with our voice assistant Riya, your recurring payment of <strong>₹${amount}</strong> for <strong>${plan}</strong> requires manual completion.</p>
        <p>Click the button below to complete the payment securely via Razorpay:</p>
        <p style="margin: 28px 0;">
          <a href="${link}" style="background-color: #2563eb; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">Pay ₹${amount} Now</a>
        </p>
        <p style="color: #64748b; font-size: 13px;">Or copy and paste this link into your browser:<br><a href="${link}">${link}</a></p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;">
        <p style="color: #94a3b8; font-size: 12px;">This is an automated notification from PayEase &amp; Razorpay.</p>
      </div>
    `,
  });

  console.log(`[Mailer] Sent to ${to}: ${info.messageId}`);
  return { ok: true, messageId: info.messageId };
}

if (require.main === module) {
  const [,, to, name, plan, amount, link] = process.argv;
  if (!to || !link) {
    console.log("Usage: node mailer.js <to_email> <name> <plan> <amount> <link>");
    process.exit(1);
  }
  sendPaymentEmail(to, name, plan, amount, link)
    .then(r => console.log(JSON.stringify(r)))
    .catch(err => {
      console.error("[Mailer Error]", err.message);
      process.exit(0);
    });
}

module.exports = { sendPaymentEmail };
