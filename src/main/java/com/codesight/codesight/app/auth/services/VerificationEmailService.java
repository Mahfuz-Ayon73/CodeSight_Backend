package com.codesight.codesight.app.auth.services;

import jakarta.mail.MessagingException;
import jakarta.mail.internet.MimeMessage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.thymeleaf.TemplateEngine;
import org.thymeleaf.context.Context;

@Service
@RequiredArgsConstructor
@Slf4j
public class VerificationEmailService {

    private final TemplateEngine templateEngine;
    private final JavaMailSender mailSender;

    @Async
    public void sendVerificationEmail(String recipientEmail, String recipientName, String token) {
        Context context = new Context();
        context.setVariable("name", recipientName);
        context.setVariable("verificationUrl", "http://localhost:8081/api/v1/auth/verify?token=" + token);

        String htmlContent = templateEngine.process("account-verification-email-template", context);
        send(recipientEmail, "Verify your CodeSight account", htmlContent);
    }

    @Async
    public void sendPasswordResetEmail(String recipientEmail, String recipientName, String token) {
        Context context = new Context();
        context.setVariable("name", recipientName);
        context.setVariable("resetUrl", "http://localhost:3000/reset-password?token=" + token);

        String htmlContent = templateEngine.process("password-reset-email-template", context);
        send(recipientEmail, "Reset your CodeSight password", htmlContent);
    }

    @Async
    public void sendInvitationEmail(String recipientEmail, String senderName, String organizationName) {
        Context context = new Context();
        context.setVariable("senderName", senderName);
        context.setVariable("organizationName", organizationName);

        String htmlContent = templateEngine.process("invitation-email-template", context);
        send(recipientEmail, "You've been invited to join " + organizationName + " on CodeSight", htmlContent);
    }

    private void send(String to, String subject, String htmlContent) {
        try {
            MimeMessage message = mailSender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(message, true, "UTF-8");
            helper.setTo(to);
            helper.setSubject(subject);
            helper.setText(htmlContent, true);
            mailSender.send(message);
            log.info("Email sent to {}: {}", to, subject);
        } catch (MessagingException e) {
            log.error("Failed to send email to {}: {}", to, e.getMessage());
            throw new RuntimeException("Failed to send email", e);
        }
    }
}
