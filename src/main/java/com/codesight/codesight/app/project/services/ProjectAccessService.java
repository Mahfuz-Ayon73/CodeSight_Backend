package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.repository.ProjectMemberRepository;
import com.codesight.codesight.common.exception.UnauthorizedException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
@RequiredArgsConstructor
public class ProjectAccessService {

    private final ProjectMemberRepository projectMemberRepository;

    /** Throws if the user is not a member of the project at all. */
    public void requireMembership(UUID projectId, UUID userId) {
        if (!projectMemberRepository.existsByProjectIdAndUserId(projectId, userId)) {
            throw new UnauthorizedException("You are not a member of this project");
        }
    }

    /** Throws if the user does not hold at least the given role. */
    public void requireRole(UUID projectId, UUID userId, ProjectMemberRole minimumRole) {
        ProjectMemberRole actual = projectMemberRepository
                .findByProjectIdAndUserId(projectId, userId)
                .orElseThrow(() -> new UnauthorizedException("You are not a member of this project"))
                .getRole();

        if (!hasAtLeast(actual, minimumRole)) {
            throw new UnauthorizedException(
                    "This action requires at least the " + minimumRole + " role");
        }
    }

    /**
     * Role hierarchy (highest → lowest): OWNER > ADMIN > MEMBER > VIEWER
     */
    private boolean hasAtLeast(ProjectMemberRole actual, ProjectMemberRole required) {
        return actual.ordinal() <= required.ordinal();
    }
}
