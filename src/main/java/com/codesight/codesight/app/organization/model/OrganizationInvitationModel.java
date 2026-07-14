package com.codesight.codesight.app.organization.model;

import com.codesight.codesight.app.project.model.ProjectMemberRole;
import jakarta.persistence.*;
import lombok.*;

import java.time.LocalDateTime;
import java.util.UUID;

@Entity
@Table(name = "organization_invitations")
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OrganizationInvitationModel {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "organization_id", nullable = false)
    private UUID organizationId;

    /** Optional — if set, accepting the invitation also enrolls the invitee in this project. */
    @Column(name = "project_id")
    private UUID projectId;

    @Column(nullable = false)
    private String email;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private OrganizationMemberRole role;

    /** Only set when projectId is set — reuses the same role picked for the org invite. */
    @Enumerated(EnumType.STRING)
    @Column(name = "project_role")
    private ProjectMemberRole projectRole;

    @Column(nullable = false, unique = true)
    private String token;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private InvitationStatus status;

    @Column(name = "invited_by_user_id", nullable = false)
    private UUID invitedByUserId;

    private LocalDateTime createdAt;

    @Column(nullable = false)
    private LocalDateTime expiresAt;

    private LocalDateTime acceptedAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
    }
}
