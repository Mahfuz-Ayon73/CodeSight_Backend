package com.codesight.codesight.common.utils;

import com.codesight.codesight.app.project.dto.ProjectResponseDto;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.user.dto.UserResponseDto;
import com.codesight.codesight.app.user.model.UserModel;

public class ObjectToDTOMapper {

    public static UserResponseDto toUserResponseDto(UserModel user) {
        if (user == null) {
            return null;
        }
        return UserResponseDto.builder()
                .id(user.getId())
                .email(user.getEmail())
                .username(user.getUsername())
                .role(user.getRole())
                .isEnabled(user.isEnabled())
                .createdAt(user.getCreatedAt())
                .updatedAt(user.getUpdatedAt())
                .build();
    }

    public static ProjectResponseDto toProjectResponseDto(ProjectModel project) {
        if (project == null) {
            return null;
        }
        return ProjectResponseDto.builder()
                .id(project.getId())
                .name(project.getName())
                .description(project.getDescription())
                .ownerId(project.getOwnerId())
                .createdAt(project.getCreatedAt())
                .updatedAt(project.getUpdatedAt())
                .build();
    }
}
