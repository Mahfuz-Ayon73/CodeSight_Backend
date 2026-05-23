package com.codesight.codesight.app.user.controllers;

import com.codesight.codesight.app.user.dto.UserResponseDto;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.services.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.UUID;

@RestController
@RequestMapping("/api/v1/users")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;

    @GetMapping("/profile")
    public ResponseEntity<UserResponseDto> getMyProfile(@AuthenticationPrincipal UserModel currentUser) {
        return ResponseEntity.ok(userService.getUserProfile(currentUser.getId()));
    }

    @GetMapping("/{id}")
    public ResponseEntity<UserResponseDto> getUserById(@PathVariable UUID id) {
        return ResponseEntity.ok(userService.getUserProfile(id));
    }
}
