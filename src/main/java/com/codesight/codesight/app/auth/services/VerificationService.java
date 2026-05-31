package com.codesight.codesight.app.auth.services;

import com.codesight.codesight.common.exception.InvalidVerificationTokenException;
import com.codesight.codesight.common.exception.TokenExpirationException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class VerificationService {

    private final JWTService jwtService;

    private static final long VERIFICATION_EXPIRATION_MS = 900_000;   // 15 minutes
    private static final long PASSWORD_RESET_EXPIRATION_MS = 900_000; // 15 minutes

    public String generateVerificationToken(String email) {
        return jwtService.generateVerificationToken(email, VERIFICATION_EXPIRATION_MS);
    }

    public String generatePasswordResetToken(String email) {
        return jwtService.generatePasswordResetToken(email, PASSWORD_RESET_EXPIRATION_MS);
    }

    public String verifyToken(String token) {
        return extractEmailForPurpose(token, "verification");
    }

    public String verifyPasswordResetToken(String token) {
        return extractEmailForPurpose(token, "password-reset");
    }

    private String extractEmailForPurpose(String token, String expectedPurpose) {
        try {
            if (jwtService.isTokenExpired(token)) {
                throw new TokenExpirationException("Token has expired");
            }
            String purpose = jwtService.extractClaim(token, claims -> claims.get("purpose", String.class));
            if (!expectedPurpose.equals(purpose)) {
                throw new InvalidVerificationTokenException("Invalid token purpose");
            }
            return jwtService.extractUsername(token);
        } catch (TokenExpirationException | InvalidVerificationTokenException e) {
            throw e;
        } catch (io.jsonwebtoken.ExpiredJwtException e) {
            throw new TokenExpirationException("Token has expired");
        } catch (Exception e) {
            throw new InvalidVerificationTokenException("Invalid token");
        }
    }
}
