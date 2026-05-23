package com.codesight.codesight.app.auth.services;

import com.codesight.codesight.common.exception.InvalidVerificationTokenException;
import com.codesight.codesight.common.exception.TokenExpirationException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class VerificationService {

    private final JWTService jwtService;

    private static final long VERIFICATION_EXPIRATION_MS = 900000; // 15 minutes

    public String generateVerificationToken(String email) {
        return jwtService.generateVerificationToken(email, VERIFICATION_EXPIRATION_MS);
    }

    public String verifyToken(String token) {
        try {
            if (jwtService.isTokenExpired(token)) {
                throw new TokenExpirationException("Verification token has expired");
            }

            String purpose = jwtService.extractClaim(token, claims -> claims.get("purpose", String.class));
            if (!"verification".equals(purpose)) {
                throw new InvalidVerificationTokenException("Invalid token purpose");
            }

            return jwtService.extractUsername(token);
        } catch (io.jsonwebtoken.ExpiredJwtException e) {
            throw new TokenExpirationException("Verification token has expired");
        } catch (Exception e) {
            throw new InvalidVerificationTokenException("Invalid verification token");
        }
    }
}
