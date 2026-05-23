package com.codesight.codesight.app.project.services;

import com.codesight.codesight.app.project.dto.ProjectRequestDto;
import com.codesight.codesight.app.project.dto.ProjectResponseDto;
import com.codesight.codesight.app.project.model.ProjectModel;
import com.codesight.codesight.app.project.repository.ProjectRepository;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.codesight.codesight.common.exception.UnauthorizedException;
import com.codesight.codesight.common.utils.ObjectToDTOMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ProjectService {

    private final ProjectRepository projectRepository;

    public ProjectResponseDto createProject(ProjectRequestDto requestDto, UUID ownerId) {
        ProjectModel project = ProjectModel.builder()
                .name(requestDto.getName())
                .description(requestDto.getDescription())
                .ownerId(ownerId)
                .build();

        ProjectModel savedProject = projectRepository.save(project);
        return ObjectToDTOMapper.toProjectResponseDto(savedProject);
    }

    public ProjectResponseDto getProjectById(UUID id) {
        ProjectModel project = projectRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found with ID: " + id));
        return ObjectToDTOMapper.toProjectResponseDto(project);
    }

    public List<ProjectResponseDto> getAllProjectsByOwner(UUID ownerId) {
        return projectRepository.findAllByOwnerId(ownerId).stream()
                .map(ObjectToDTOMapper::toProjectResponseDto)
                .collect(Collectors.toList());
    }

    public void deleteProject(UUID id, UUID ownerId) {
        ProjectModel project = projectRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("Project not found with ID: " + id));

        if (!project.getOwnerId().equals(ownerId)) {
            throw new UnauthorizedException("You are not authorized to delete this project");
        }

        projectRepository.delete(project);
    }
}
