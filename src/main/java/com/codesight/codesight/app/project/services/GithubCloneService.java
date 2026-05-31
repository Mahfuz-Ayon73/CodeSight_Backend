package com.codesight.codesight.app.project.services;

import com.codesight.codesight.common.exception.BadRequestException;
import org.eclipse.jgit.api.Git;
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

    public void cloneRepository(String githubUrl, Path destination) {
        String normalizedUrl = normalizeGithubUrl(githubUrl);
        try {
            Git.cloneRepository()
                    .setURI(normalizedUrl)
                    .setDirectory(destination.toFile())
                    .setCloneAllBranches(false)
                    .call()
                    .close();
        } catch (Exception ex) {
            throw new RuntimeException("Failed to clone GitHub repository: " + ex.getMessage(), ex);
        }
    }
}
