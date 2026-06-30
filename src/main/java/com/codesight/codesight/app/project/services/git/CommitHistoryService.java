package com.codesight.codesight.app.project.services.git;

import com.codesight.codesight.app.project.dto.graph.CommitDiffDto;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.eclipse.jgit.api.Git;
import org.eclipse.jgit.diff.DiffEntry;
import org.eclipse.jgit.diff.DiffFormatter;
import org.eclipse.jgit.lib.ObjectId;
import org.eclipse.jgit.lib.ObjectReader;
import org.eclipse.jgit.lib.PersonIdent;
import org.eclipse.jgit.lib.Repository;
import org.eclipse.jgit.revwalk.RevCommit;
import org.eclipse.jgit.revwalk.RevWalk;
import org.eclipse.jgit.treewalk.AbstractTreeIterator;
import org.eclipse.jgit.treewalk.CanonicalTreeParser;
import org.eclipse.jgit.treewalk.EmptyTreeIterator;
import org.eclipse.jgit.util.io.DisabledOutputStream;
import org.springframework.stereotype.Service;

import java.io.File;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class CommitHistoryService {

    private final ProjectRepository projectRepository;

    /**
     * Returns the last {@code count} commits for the project's cloned repository,
     * each including a file-level diff vs its parent commit.
     */
    public List<CommitDiffDto> getLastNCommits(UUID organizationId, UUID projectId, int count) {
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));

        if (project.getStoragePath() == null) {
            throw new ResourceNotFoundException("No codebase found for this project — upload one first");
        }

        File repoDir = new File(project.getStoragePath());
        if (!repoDir.exists() || !new File(repoDir, ".git").exists()) {
            log.warn("[HISTORY] No .git directory at {}", repoDir);
            return List.of();
        }

        List<CommitDiffDto> result = new ArrayList<>();
        try (Git git = Git.open(repoDir);
             Repository repo = git.getRepository()) {

            Iterable<RevCommit> commits = git.log().setMaxCount(count).call();

            try (RevWalk revWalk = new RevWalk(repo)) {
                for (RevCommit commit : commits) {
                    CommitDiffDto dto = buildCommitDiff(repo, revWalk, commit);
                    result.add(dto);
                }
            }
        } catch (Exception e) {
            log.error("[HISTORY] Failed to read git history for project {}", projectId, e);
        }

        return result;
    }

    private CommitDiffDto buildCommitDiff(Repository repo, RevWalk revWalk, RevCommit commit) {
        List<String> added    = new ArrayList<>();
        List<String> modified = new ArrayList<>();
        List<String> deleted  = new ArrayList<>();

        try (DiffFormatter formatter = new DiffFormatter(DisabledOutputStream.INSTANCE)) {
            formatter.setRepository(repo);
            formatter.setDetectRenames(true);

            AbstractTreeIterator oldTree = resolveParentTree(repo, revWalk, commit);
            AbstractTreeIterator newTree = resolveTree(repo, commit.getTree());

            List<DiffEntry> diffs = formatter.scan(oldTree, newTree);
            for (DiffEntry entry : diffs) {
                switch (entry.getChangeType()) {
                    case ADD    -> added.add(entry.getNewPath());
                    case MODIFY, RENAME, COPY -> modified.add(entry.getNewPath());
                    case DELETE -> deleted.add(entry.getOldPath());
                }
            }
        } catch (Exception e) {
            log.warn("[HISTORY] Could not compute diff for commit {}: {}", commit.getName(), e.getMessage());
        }

        PersonIdent author = commit.getAuthorIdent();
        LocalDateTime timestamp = LocalDateTime.ofInstant(
                Instant.ofEpochSecond(commit.getCommitTime()), ZoneId.systemDefault());

        String sha = commit.getName();
        return CommitDiffDto.builder()
                .sha(sha)
                .shortSha(sha.substring(0, Math.min(7, sha.length())))
                .message(commit.getShortMessage())
                .author(author != null ? author.getName() : "Unknown")
                .timestamp(timestamp)
                .addedFiles(added)
                .modifiedFiles(modified)
                .deletedFiles(deleted)
                .totalChanges(added.size() + modified.size() + deleted.size())
                .build();
    }

    private AbstractTreeIterator resolveParentTree(Repository repo, RevWalk revWalk, RevCommit commit) {
        try {
            if (commit.getParentCount() == 0) {
                return new EmptyTreeIterator();
            }
            RevCommit parent = revWalk.parseCommit(commit.getParent(0).getId());
            return resolveTree(repo, parent.getTree());
        } catch (Exception e) {
            return new EmptyTreeIterator();
        }
    }

    private AbstractTreeIterator resolveTree(Repository repo, org.eclipse.jgit.lib.AnyObjectId treeId) throws Exception {
        try (ObjectReader reader = repo.newObjectReader()) {
            CanonicalTreeParser parser = new CanonicalTreeParser();
            ObjectId resolved = repo.resolve(treeId.getName() + "^{tree}");
            if (resolved == null) {
                parser.reset(reader, treeId);
            } else {
                parser.reset(reader, resolved);
            }
            return parser;
        }
    }

    /**
     * Returns the HEAD commit SHA for the project's cloned repository.
     * Returns null if no git repo or if the repo has no commits.
     */
    public String getHeadCommitSha(UUID organizationId, UUID projectId) {
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));

        if (project.getStoragePath() == null) return null;
        File repoDir = new File(project.getStoragePath());
        if (!repoDir.exists() || !new File(repoDir, ".git").exists()) return null;

        try (Git git = Git.open(repoDir)) {
            ObjectId head = git.getRepository().resolve("HEAD");
            if (head == null) return null;
            try (RevWalk walk = new RevWalk(git.getRepository())) {
                RevCommit commit = walk.parseCommit(head);
                return commit.getName();
            }
        } catch (Exception e) {
            log.warn("[HISTORY] Could not resolve HEAD for project {}: {}", projectId, e.getMessage());
            return null;
        }
    }

    /**
     * Returns metadata for a specific commit SHA (message, author, timestamp).
     * Returns null if the commit is not found.
     */
    public CommitDiffDto getCommitInfo(UUID organizationId, UUID projectId, String sha) {
        ProjectModel project = projectRepository.findByIdAndOrganizationId(projectId, organizationId)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found"));

        if (project.getStoragePath() == null) return null;
        File repoDir = new File(project.getStoragePath());
        if (!repoDir.exists() || !new File(repoDir, ".git").exists()) return null;

        try (Git git = Git.open(repoDir);
             Repository repo = git.getRepository();
             RevWalk walk = new RevWalk(repo)) {
            ObjectId id = repo.resolve(sha);
            if (id == null) return null;
            RevCommit commit = walk.parseCommit(id);
            return buildCommitDiff(repo, walk, commit);
        } catch (Exception e) {
            log.warn("[HISTORY] Could not load commit {} for project {}: {}", sha, projectId, e.getMessage());
            return null;
        }
    }
}
