package com.codesight.codesight.app.auth.services;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.thymeleaf.TemplateEngine;
import org.thymeleaf.context.Context;

@Service
@RequiredArgsConstructor
@Slf4j
public class VerificationEmailService {

    private final TemplateEngine templateEngine;

    public void sendVerificationEmail(String recipientEmail, String recipientName, String token) {
        Context context = new Context();
        context.setVariable("name", recipientName);
        context.setVariable("verificationUrl", "http://localhost:8081/api/v1/auth/verify?token=" + token);

        String htmlContent = templateEngine.process("account-verification-email-template", context);

        log.info("\n=== [SIMULATED EMAIL SENT TO: {}] ===\n{}\n======================================\n", recipientEmail, htmlContent);
    }

    public void sendInvitationEmail(String recipientEmail, String senderName, String organizationName) {
        Context context = new Context();
        context.setVariable("senderName", senderName);
        context.setVariable("organizationName", organizationName);

        String htmlContent = templateEngine.process("invitation-email-template", context);

        log.info("\n=== [SIMULATED EMAIL SENT TO: {}] ===\n{}\n======================================\n", recipientEmail, htmlContent);
    }
}
