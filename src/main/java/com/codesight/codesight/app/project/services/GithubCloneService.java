package com.codesight.codesight.app.project.services;

import com.codesight.codesight.common.exception.BadRequestException;
import org.eclipse.jgit.api.Git;
import org.eclipse.jgit.api.errors.GitAPIException;
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

    public void cloneRepository(String githubUrl, Path destination) throws GitAPIException {
        String normalizedUrl = normalizeGithubUrl(githubUrl);
        Git.cloneRepository()
                .setURI(normalizedUrl)
                .setDirectory(destination.toFile())
                .setCloneAllBranches(false)
                .call()
                .close();
    }
}
