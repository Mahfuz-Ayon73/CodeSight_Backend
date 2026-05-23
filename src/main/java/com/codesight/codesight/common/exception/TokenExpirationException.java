package com.codesight.codesight.common.exception;

public class TokenExpirationException extends RuntimeException {
    public TokenExpirationException(String message) {
        super(message);
    }
}
