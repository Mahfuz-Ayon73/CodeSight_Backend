package com.codesight.codesight.app.auth.services;

import com.codesight.codesight.app.user.dto.UserResponseDto;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.repository.UserRepository;
import com.codesight.codesight.app.user.role.UserRole;
import com.codesight.codesight.common.exception.BadCredentialsException;
import com.codesight.codesight.common.exception.BadRequestException;
import com.codesight.codesight.common.exception.EmailNotVerifiedException;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.codesight.codesight.common.exception.UserAlreadyExistException;
import com.codesight.codesight.common.utils.ObjectToDTOMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JWTService jwtService;
    private final VerificationService verificationService;
    private final VerificationEmailService emailService;
    private final AuthenticationManager authenticationManager;

    public UserResponseDto register(String firstName, String lastName, String email, String password) {
        if (userRepository.findByEmail(email).isPresent()) {
            throw new UserAlreadyExistException("Email already in use: " + email);
        }

        String generatedUsername = generateUniqueUsername(firstName, lastName);

        UserModel user = UserModel.builder()
                .email(email)
                .password(passwordEncoder.encode(password))
                .firstName(firstName)
                .lastName(lastName)
                .handle(generatedUsername)
                .role(UserRole.USER)
                .isEnabled(false)
                .build();

        UserModel savedUser = userRepository.save(user);

        String verificationToken = verificationService.generateVerificationToken(savedUser.getEmail());
        emailService.sendVerificationEmail(savedUser.getEmail(), savedUser.getFirstName(), verificationToken);

        return ObjectToDTOMapper.toUserResponseDto(savedUser);
    }

    public Map<String, Object> login(String email, String password) {
        try {
            authenticationManager.authenticate(
                    new UsernamePasswordAuthenticationToken(email, password)
            );
        } catch (org.springframework.security.authentication.DisabledException e) {
            throw new EmailNotVerifiedException("Please verify your email address before logging in");
        } catch (org.springframework.security.core.AuthenticationException e) {
            throw new BadCredentialsException("Invalid email or password");
        }

        UserModel user = userRepository.findByEmail(email)
                .orElseThrow(() -> new BadCredentialsException("Invalid email or password"));

        if (!user.isEnabled()) {
            throw new EmailNotVerifiedException("Please verify your email address before logging in");
        }

        String jwtToken = jwtService.generateToken(user);

        Map<String, Object> response = new HashMap<>();
        response.put("token", jwtToken);
        response.put("user", ObjectToDTOMapper.toUserResponseDto(user));
        return response;
    }

    public void verifyEmail(String token) {
        String email = verificationService.verifyToken(token);
        UserModel user = userRepository.findByEmail(email)
                .orElseThrow(() -> new BadCredentialsException("User not found for this verification token"));

        if (user.isEnabled()) {
            throw new BadRequestException("Email is already verified");
        }

        user.setEnabled(true);
        userRepository.save(user);
    }

    public void resendVerificationEmail(String email) {
        UserModel user = userRepository.findByEmail(email)
                .orElseThrow(() -> new ResourceNotFoundException("No account found with that email"));

        if (user.isEnabled()) {
            throw new BadRequestException("Email is already verified");
        }

        String verificationToken = verificationService.generateVerificationToken(user.getEmail());
        emailService.sendVerificationEmail(user.getEmail(), user.getFirstName(), verificationToken);
    }

    public void forgotPassword(String email) {
        // Always return success to avoid user enumeration
        userRepository.findByEmail(email).ifPresent(user -> {
            String resetToken = verificationService.generatePasswordResetToken(user.getEmail());
            emailService.sendPasswordResetEmail(user.getEmail(), user.getFirstName(), resetToken);
        });
    }

    public void resetPassword(String token, String newPassword) {
        String email = verificationService.verifyPasswordResetToken(token);
        UserModel user = userRepository.findByEmail(email)
                .orElseThrow(() -> new BadCredentialsException("User not found for this reset token"));

        user.setPassword(passwordEncoder.encode(newPassword));
        userRepository.save(user);
    }

    // -------------------------------------------------------------------------

    private String generateUniqueUsername(String firstName, String lastName) {
        String base = (safeSlug(firstName) + "." + safeSlug(lastName)).replaceAll("^\\.|\\.$", "");
        if (base.isBlank()) base = "user";

        String candidate = base;
        int suffix = 1;
        while (userRepository.existsByHandle(candidate)) {
            candidate = base + suffix++;
        }
        return candidate;
    }

    private String safeSlug(String value) {
        if (value == null) return "";
        return value.trim().toLowerCase().replaceAll("[^a-z0-9]+", "");
    }
}
