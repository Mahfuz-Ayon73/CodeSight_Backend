package com.codesight.codesight.app.auth.services;

import com.codesight.codesight.app.user.dto.UserResponseDto;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.repository.UserRepository;
import com.codesight.codesight.app.user.role.UserRole;
import com.codesight.codesight.common.exception.BadCredentialsException;
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

    public UserResponseDto register(String username, String email, String password, UserRole role) {
        if (userRepository.findByEmail(email).isPresent()) {
            throw new UserAlreadyExistException("Email already in use: " + email);
        }

        UserModel user = UserModel.builder()
                .username(username)
                .email(email)
                .password(passwordEncoder.encode(password))
                .role(role == null ? UserRole.USER : role)
                .isEnabled(false) // Must be verified
                .build();

        UserModel savedUser = userRepository.save(user);

        String verificationToken = verificationService.generateVerificationToken(savedUser.getEmail());
        emailService.sendVerificationEmail(savedUser.getEmail(), savedUser.getUsername(), verificationToken);

        return ObjectToDTOMapper.toUserResponseDto(savedUser);
    }

    public Map<String, Object> login(String email, String password) {
        try {
            authenticationManager.authenticate(
                    new UsernamePasswordAuthenticationToken(email, password)
            );
        } catch (org.springframework.security.core.AuthenticationException e) {
            throw new BadCredentialsException("Invalid email or password");
        }

        UserModel user = userRepository.findByEmail(email)
                .orElseThrow(() -> new BadCredentialsException("Invalid email or password"));

        if (!user.isEnabled()) {
            throw new BadCredentialsException("Please verify your email address before logging in");
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

        user.setEnabled(true);
        userRepository.save(user);
    }
}
