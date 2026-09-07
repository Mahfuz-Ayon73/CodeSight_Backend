package com.codesight.codesight.app.project.services.graph;

import com.codesight.codesight.app.project.dto.graph.ClusterNoteDto;
import com.codesight.codesight.app.project.dto.graph.ClusterNoteRequest;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.model.graph.ClusterNote;
import com.codesight.codesight.app.project.model.graph.GraphSnapshot;
import com.codesight.codesight.app.project.repository.ProjectMemberRepository;
import com.codesight.codesight.app.project.repository.graph.ClusterNoteRepository;
import com.codesight.codesight.app.project.repository.graph.GraphSnapshotRepository;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.repository.UserRepository;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.codesight.codesight.common.exception.UnauthorizedException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

/**
 * Adds, lists, and deletes {@link ClusterNote} rows — the MEMBER-tier, additive
 * sibling of {@link ClusterOverrideService}'s ADMIN/OWNER-only rename/re-summary.
 */
@Service
@RequiredArgsConstructor
public class ClusterNoteService {

    private final ClusterNoteRepository noteRepository;
    private final GraphSnapshotRepository snapshotRepository;
    private final ProjectMemberRepository projectMemberRepository;
    private final UserRepository userRepository;

    @Transactional
    public ClusterNoteDto addNote(UUID projectId, ClusterNoteRequest request, UUID userId) {
        GraphSnapshot snapshot = snapshotRepository.findById(request.getSnapshotId())
                .orElseThrow(() -> new ResourceNotFoundException("Snapshot not found"));

        if (!snapshot.getProjectId().equals(projectId)) {
            throw new ResourceNotFoundException("Snapshot not found");
        }

        UserModel author = userRepository.findById(userId)
                .orElseThrow(() -> new ResourceNotFoundException("User not found"));

        ClusterNote note = ClusterNote.builder()
                .projectId(projectId)
                .snapshotId(request.getSnapshotId())
                .clusterId(request.getClusterId())
                .content(request.getContent().trim())
                .authorId(userId)
                .authorName(displayName(author))
                .build();

        return toDto(noteRepository.save(note));
    }

    public List<ClusterNoteDto> listNotes(UUID projectId, UUID snapshotId) {
        GraphSnapshot snapshot = snapshotRepository.findById(snapshotId)
                .orElseThrow(() -> new ResourceNotFoundException("Snapshot not found"));

        if (!snapshot.getProjectId().equals(projectId)) {
            throw new ResourceNotFoundException("Snapshot not found");
        }

        return noteRepository.findBySnapshotIdOrderByCreatedAtAsc(snapshotId).stream()
                .map(this::toDto)
                .toList();
    }

    @Transactional
    public void deleteNote(UUID projectId, Long noteId, UUID requesterId) {
        ClusterNote note = noteRepository.findById(noteId)
                .orElseThrow(() -> new ResourceNotFoundException("Note not found"));

        if (!note.getProjectId().equals(projectId)) {
            throw new ResourceNotFoundException("Note not found");
        }

        if (!note.getAuthorId().equals(requesterId) && !isAdminOrOwner(projectId, requesterId)) {
            throw new UnauthorizedException("Only the note's author or an ADMIN/OWNER can delete it");
        }

        noteRepository.delete(note);
    }

    private boolean isAdminOrOwner(UUID projectId, UUID userId) {
        return projectMemberRepository.findByProjectIdAndUserId(projectId, userId)
                .map(m -> m.getRole() == ProjectMemberRole.ADMIN || m.getRole() == ProjectMemberRole.OWNER)
                .orElse(false);
    }

    private String displayName(UserModel user) {
        String full = ((user.getFirstName() == null ? "" : user.getFirstName()) + " "
                + (user.getLastName() == null ? "" : user.getLastName())).trim();
        return full.isEmpty() ? user.getEmail() : full;
    }

    private ClusterNoteDto toDto(ClusterNote n) {
        return ClusterNoteDto.builder()
                .id(n.getId())
                .clusterId(n.getClusterId())
                .content(n.getContent())
                .authorId(n.getAuthorId().toString())
                .authorName(n.getAuthorName())
                .createdAt(n.getCreatedAt())
                .build();
    }
}
