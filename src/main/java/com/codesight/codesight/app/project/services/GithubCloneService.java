package com.codesight.codesight.app.project.services;

import com.codesight.codesight.common.exception.BadRequestException;
import org.eclipse.jgit.api.Git;
import org.eclipse.jgit.transport.UsernamePasswordCredentialsProvider;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.regex.Pattern;

@Service
public class GithubCloneService {

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
            trimmed = trimmed.endsWith("/") ? trimmed + ".git" : trimmed + ".git";
        }

        return trimmed;
    }

    /**
     * Clone a repository. Pass a GitHub PAT as accessToken for private repos.
     * For public repos, pass null.
     */
    public void cloneRepository(String githubUrl, Path destination, String accessToken) {
        String normalizedUrl = normalizeGithubUrl(githubUrl);
        try {
            var cloneCommand = Git.cloneRepository()
                    .setURI(normalizedUrl)
                    .setDirectory(destination.toFile())
                    .setCloneAllBranches(false);

            if (accessToken != null && !accessToken.isBlank()) {
                // GitHub PAT: use token as password, "oauth2" or empty string as username
                cloneCommand.setCredentialsProvider(
                    new UsernamePasswordCredentialsProvider("oauth2", accessToken)
                );
            }

            cloneCommand.call().close();
        } catch (Exception ex) {
            String message = ex.getMessage() != null ? ex.getMessage() : ex.getClass().getSimpleName();
            if (message.contains("not authorized") || message.contains("Authentication")) {
                throw new RuntimeException(
                    "Repository is private or URL is incorrect. Provide a GitHub Personal Access Token.", ex
                );
            }
            throw new RuntimeException("Failed to clone GitHub repository: " + message, ex);
        }
    }

    /** Overload for public repos — no token needed. */
    public void cloneRepository(String githubUrl, Path destination) {
        cloneRepository(githubUrl, destination, null);
    }
}
