package com.codesight.codesight.app.project.services;

import com.codesight.codesight.common.exception.BadRequestException;
import org.eclipse.jgit.api.Git;
import org.eclipse.jgit.api.errors.TransportException;
import org.eclipse.jgit.lib.ProgressMonitor;
import org.eclipse.jgit.transport.UsernamePasswordCredentialsProvider;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.regex.Pattern;

@Service
public class GithubCloneService {

    private static final Logger log = LoggerFactory.getLogger(GithubCloneService.class);

    private static final Pattern GITHUB_URL_PATTERN = Pattern.compile(
            "^https?://(www\\.)?github\\.com/[\\w.-]+/[\\w.-]+(?:\\.git)?/?$",
            Pattern.CASE_INSENSITIVE
    );

    public String normalizeGithubUrl(String githubUrl) {
        if (githubUrl == null || githubUrl.isBlank()) {
            throw new BadRequestException("GitHub URL is required");
        }

        String trimmed = githubUrl.trim();
        if (!GITHUB_URL_PATTERN.matcher(trimmed).matches()) {
            throw new BadRequestException("Invalid GitHub repository URL");
        }

        if (!trimmed.endsWith(".git")) {
            trimmed = trimmed.endsWith("/") ? trimmed.substring(0, trimmed.length() - 1) + ".git" : trimmed + ".git";
        }

        return trimmed;
    }

    /**
     * Clone a repository. Pass a GitHub PAT as accessToken for private repos.
     * For public repos, pass null.
     */
    public void cloneRepository(String githubUrl, Path destination, String accessToken) {
        cloneRepository(githubUrl, destination, accessToken, null);
    }

    /**
     * Clone depth — shallow enough to stay fast on large/old repos, deep enough
     * to cover the commit timeline (last {@code count=10} requested by the
     * frontend, see DashboardGraphPreview.tsx) with margin. The access token
     * isn't persisted past this call, so this is the only place commit depth
     * can be set — there's no credential left to do a later "unshallow" fetch.
     */
    private static final int CLONE_DEPTH = 30;

    /**
     * Clone a repository, reporting live progress via the given monitor.
     * Shallow (depth-limited, not full history) — analysis only needs the
     * current file tree, and a bounded depth keeps large/old repos fast.
     */
    public void cloneRepository(String githubUrl, Path destination, String accessToken, ProgressMonitor progressMonitor) {
        String normalizedUrl = normalizeGithubUrl(githubUrl);
        try {
            var cloneCommand = Git.cloneRepository()
                    .setURI(normalizedUrl)
                    .setDirectory(destination.toFile())
                    .setCloneAllBranches(false)
                    .setDepth(CLONE_DEPTH);

            if (progressMonitor != null) {
                cloneCommand.setProgressMonitor(progressMonitor);
            }

            if (accessToken != null && !accessToken.isBlank()) {
                // GitHub PATs: use "x-access-token" as username, token as password
                cloneCommand.setCredentialsProvider(
                    new UsernamePasswordCredentialsProvider("x-access-token", accessToken)
                );
            }

            cloneCommand.call().close();
        } catch (TransportException ex) {
            log.error("GitHub clone transport error: {}", ex.getMessage(), ex);
            String msg = ex.getMessage() != null ? ex.getMessage() : "";
            if (msg.contains("401") || msg.contains("not authorized") || msg.contains("Authentication")
                    || msg.contains("not permitted") || msg.contains("403")) {
                throw new BadRequestException(
                    "Authentication failed. Check that your token has the 'repo' scope and is valid."
                );
            }
            if (msg.contains("Repository not found") || msg.contains("not found")) {
                throw new BadRequestException(
                    "Repository not found. Verify the URL is correct and the token has access."
                );
            }
            throw new BadRequestException("GitHub clone failed: " + msg);
        } catch (Exception ex) {
            log.error("GitHub clone error: {}", ex.getMessage(), ex);
            String message = ex.getMessage() != null ? ex.getMessage() : ex.getClass().getSimpleName();
            throw new BadRequestException("Failed to clone GitHub repository: " + message);
        }
    }

    /** Overload for public repos — no token needed. */
    public void cloneRepository(String githubUrl, Path destination) {
        cloneRepository(githubUrl, destination, null);
    }
}
