package com.codesight.codesight.app.user.services;

import com.codesight.codesight.app.user.dto.UserResponseDto;
import com.codesight.codesight.app.user.model.UserModel;

import java.util.UUID;

public interface UserService {
    UserModel findById(UUID id);
    UserModel findByEmail(String email);
    UserModel save(UserModel user);
    UserResponseDto getUserProfile(UUID id);
    void changePassword(UUID id, String currentPassword, String newPassword);
    void setLastOrganization(UUID id, UUID organizationId);
}
