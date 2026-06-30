package com.codesight.codesight.app.project.model;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDateTime;
import java.util.UUID;

@Entity
@Table(name = "projects")
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ProjectModel {
    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(nullable = false)
    private String name;

    private String description;

    @Column(nullable = false)
    private UUID organizationId;

    @Column(nullable = false)
    private UUID ownerId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    @Builder.Default
    private ProjectSourceType sourceType = ProjectSourceType.LOCAL_ZIP;

    private String githubUrl;

    /** Absolute path to extracted/cloned repository on disk */
    @Column(length = 1024)
    private String storagePath;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    @Builder.Default
    private AnalysisStatus analysisStatus = AnalysisStatus.PENDING_UPLOAD;

    @Column(length = 2048)
    private String uploadErrorMessage;

    /** Canvas-level cluster merge overrides stored as JSON array of ClusterMerge objects. */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "user_merges_json", columnDefinition = "jsonb")
    @Builder.Default
    private String userMergesJson = "[]";

    private LocalDateTime uploadedAt;
    private LocalDateTime analysisCompletedAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
