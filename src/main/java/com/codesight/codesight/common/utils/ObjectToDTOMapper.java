package com.codesight.codesight.common.utils;

import com.codesight.codesight.app.organization.dto.OrganizationResponseDto;
import com.codesight.codesight.app.organization.model.OrganizationModel;
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
                .username(user.getHandle())
                .firstName(user.getFirstName())
                .lastName(user.getLastName())
                .role(user.getRole())
                .isEnabled(user.isEnabled())
                .createdAt(user.getCreatedAt())
                .updatedAt(user.getUpdatedAt())
                .build();
    }

    public static OrganizationResponseDto toOrganizationResponseDto(OrganizationModel organization) {
        if (organization == null) {
            return null;
        }
        return OrganizationResponseDto.builder()
                .id(organization.getId())
                .name(organization.getName())
                .slug(organization.getSlug())
                .createdByUserId(organization.getCreatedByUserId())
                .createdAt(organization.getCreatedAt())
                .updatedAt(organization.getUpdatedAt())
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
                .organizationId(project.getOrganizationId())
                .ownerId(project.getOwnerId())
                .sourceType(project.getSourceType())
                .githubUrl(project.getGithubUrl())
                .analysisStatus(project.getAnalysisStatus())
                .uploadErrorMessage(project.getUploadErrorMessage())
                .uploadedAt(project.getUploadedAt())
                .createdAt(project.getCreatedAt())
                .updatedAt(project.getUpdatedAt())
                .build();
    }
}
