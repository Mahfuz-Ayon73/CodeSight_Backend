package com.codesight.codesight.app.auth.services;

import org.junit.jupiter.api.Test;
import org.thymeleaf.context.Context;
import org.thymeleaf.spring6.SpringTemplateEngine;
import org.thymeleaf.templateresolver.ClassLoaderTemplateResolver;

import static org.assertj.core.api.Assertions.assertThat;

class VerificationEmailTemplateTest {

    @Test
    void rendersRecipientAndVerificationLink() {
        ClassLoaderTemplateResolver resolver = new ClassLoaderTemplateResolver();
        resolver.setPrefix("templates/");
        resolver.setSuffix(".html");
        resolver.setTemplateMode("HTML");

        SpringTemplateEngine templateEngine = new SpringTemplateEngine();
        templateEngine.setTemplateResolver(resolver);

        Context context = new Context();
        context.setVariable("name", "Ada");
        context.setVariable("verificationUrl", "http://localhost:3000/verify-email?token=test-token");

        String rendered = templateEngine.process("account-verification-email-template", context);

        assertThat(rendered)
                .contains("Welcome to CodeSight, <span>Ada</span>.")
                .contains("http://localhost:3000/verify-email?token=test-token")
                .contains("This link expires in 15 minutes.")
                .doesNotContain("${name}", "${verificationUrl}");
    }
}
