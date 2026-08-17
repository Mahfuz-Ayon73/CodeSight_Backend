package com.codesight.codesight.app.project.services.git;

import com.codesight.codesight.app.project.dto.graph.AuthorShareDto;
import com.codesight.codesight.app.project.dto.graph.FileOwnershipDto;
import com.codesight.codesight.app.project.dto.graph.OwnershipResponse;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.eclipse.jgit.api.Git;
import org.eclipse.jgit.blame.BlameResult;
import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.lib.PersonIdent;
import org.eclipse.jgit.lib.Repository;
import org.springframework.stereotype.Service;

import java.io.File;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Computes per-file git-blame ownership as of HEAD — how many of a file's
 * current lines trace back to each author. This is "who owns this code now",
 * distinct from {@link CommitHistoryService} which reports "who committed
 * recently". The frontend aggregates the per-file results up to cluster
 * level itself (same division of labor as the commit-diff overlay), so this
 * service only ever deals in individual file paths.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ClusterOwnershipService {

    /** Hard cap on files blamed per request — protects against pathological requests
     *  (a huge blueprint) turning a single call into a multi-minute blame sweep. */
    private static final int MAX_FILES = 2000;

    private final ProjectRepository projectRepository;

    public OwnershipResponse computeOwnership(UUID organizationId, UUID projectId, List<String> paths) {
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));

        if (project.getStoragePath() == null) {
            return OwnershipResponse.builder().files(List.of()).truncated(false).build();
        }

        File repoDir = new File(project.getStoragePath());
        if (!repoDir.exists() || !new File(repoDir, ".git").exists()) {
            log.warn("[OWNERSHIP] No .git directory at {}", repoDir);
            return OwnershipResponse.builder().files(List.of()).truncated(false).build();
        }

        boolean truncated = paths.size() > MAX_FILES;
        List<String> effectivePaths = truncated ? paths.subList(0, MAX_FILES) : paths;

        List<FileOwnershipDto> files = new ArrayList<>();
        try (Git git = Git.open(repoDir)) {
            Repository repo = git.getRepository();
            ObjectId head = repo.resolve("HEAD");
            if (head == null) {
                return OwnershipResponse.builder().files(List.of()).truncated(false).build();
            }

            for (String path : effectivePaths) {
                FileOwnershipDto dto = blameFile(git, head, path);
                if (dto != null) files.add(dto);
            }
        } catch (Exception e) {
            log.error("[OWNERSHIP] Failed to compute ownership for project {}", projectId, e);
        }

        return OwnershipResponse.builder().files(files).truncated(truncated).build();
    }

    private FileOwnershipDto blameFile(Git git, ObjectId head, String path) {
        try {
            BlameResult blame = git.blame()
                    .setStartCommit(head)
                    .setFollowFileRenames(true)
                    .setFilePath(path)
                    .call();
            if (blame == null) return null;

            int lineCount = blame.getResultContents().size();
            if (lineCount == 0) return null;

            // key = "name|email" so two authors sharing a display name don't merge.
            Map<String, int[]> lineCounts = new LinkedHashMap<>();
            Map<String, String> nameByKey = new LinkedHashMap<>();
            Map<String, String> emailByKey = new LinkedHashMap<>();
            int attributed = 0;
            for (int i = 0; i < lineCount; i++) {
                PersonIdent who = blame.getSourceAuthor(i);
                if (who == null) continue;
                String name = who.getName();
                String email = who.getEmailAddress();
                String key = name + "|" + email;
                lineCounts.computeIfAbsent(key, k -> new int[1])[0]++;
                nameByKey.putIfAbsent(key, name);
                emailByKey.putIfAbsent(key, email);
                attributed++;
            }
            if (attributed == 0) return null;

            final int total = attributed;
            List<AuthorShareDto> authors = lineCounts.entrySet().stream()
                    .map(e -> AuthorShareDto.builder()
                            .name(nameByKey.get(e.getKey()))
                            .email(emailByKey.get(e.getKey()))
                            .lines(e.getValue()[0])
                            .percentage(round1(100.0 * e.getValue()[0] / total))
                            .build())
                    .sorted(Comparator.comparingInt(AuthorShareDto::getLines).reversed())
                    .toList();

            AuthorShareDto primary = authors.get(0);
            return FileOwnershipDto.builder()
                    .path(path)
                    .authors(authors)
                    .primaryOwner(primary.getName())
                    .primaryOwnerEmail(primary.getEmail())
                    .primaryOwnerPercentage(primary.getPercentage())
                    .totalLines(total)
                    .build();
        } catch (Exception e) {
            // Missing/binary/never-committed files are expected (blueprint paths can
            // reference generated or untracked files) — skip rather than fail the batch.
            log.debug("[OWNERSHIP] blame skipped for {}: {}", path, e.getMessage());
            return null;
        }
    }

    private static double round1(double v) {
        return Math.round(v * 10) / 10.0;
    }
}
