package com.codesight.codesight.app.project.controllers;

import com.codesight.codesight.app.project.dto.ProjectMemberResponseDto;
import com.codesight.codesight.app.project.model.ProjectMemberRole;
import com.codesight.codesight.app.project.services.ProjectMemberService;
import com.codesight.codesight.app.auth.services.JWTService;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.role.UserRole;
import com.codesight.codesight.common.exception.UnauthorizedException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = ProjectMemberController.class)
@AutoConfigureMockMvc(addFilters = false)
class ProjectMemberControllerIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private ProjectMemberService projectMemberService;

    // JWTAuthenticationFilter is discovered by the MVC slice even though
    // filters are disabled for MockMvc requests; provide its collaborators so
    // the focused web context can still be constructed.
    @MockitoBean
    private JWTService jwtService;

    @MockitoBean
    private UserDetailsService userDetailsService;

    private final UUID organizationId = UUID.randomUUID();
    private final UUID projectId = UUID.randomUUID();
    private final UUID currentUserId = UUID.randomUUID();

    @BeforeEach
    void authenticateRequest() {
        UserModel currentUser = UserModel.builder()
                .id(currentUserId)
                .email("owner@example.com")
                .password("not-used")
                .firstName("Project")
                .lastName("Owner")
                .handle("project-owner")
                .role(UserRole.USER)
                .isEnabled(true)
                .build();
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        currentUser,
                        null,
                        currentUser.getAuthorities()
                )
        );
    }

    @AfterEach
    void clearAuthentication() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void listMembersReturnsTheServiceResponseAsJson() throws Exception {
        UUID memberId = UUID.randomUUID();
        when(projectMemberService.listMembers(organizationId, projectId, currentUserId))
                .thenReturn(List.of(ProjectMemberResponseDto.builder()
                        .id(UUID.randomUUID())
                        .projectId(projectId)
                        .userId(memberId)
                        .userEmail("member@example.com")
                        .userFirstName("Team")
                        .userLastName("Member")
                        .role(ProjectMemberRole.MEMBER)
                        .joinedAt(LocalDateTime.of(2026, 1, 2, 3, 4))
                        .build()));

        mockMvc.perform(get(memberPath()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].projectId").value(projectId.toString()))
                .andExpect(jsonPath("$[0].userId").value(memberId.toString()))
                .andExpect(jsonPath("$[0].userEmail").value("member@example.com"))
                .andExpect(jsonPath("$[0].role").value("MEMBER"));
    }

    @Test
    void inviteMemberValidatesAndCreatesAMember() throws Exception {
        UUID invitedUserId = UUID.randomUUID();
        when(projectMemberService.inviteMember(
                any(UUID.class),
                any(UUID.class),
                any(UUID.class),
                any()
        )).thenReturn(ProjectMemberResponseDto.builder()
                .id(UUID.randomUUID())
                .projectId(projectId)
                .userId(invitedUserId)
                .userEmail("invitee@example.com")
                .role(ProjectMemberRole.VIEWER)
                .build());

        mockMvc.perform(post(memberPath())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"invitee@example.com","role":"VIEWER"}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value(invitedUserId.toString()))
                .andExpect(jsonPath("$.role").value("VIEWER"));
    }

    @Test
    void inviteMemberReturnsBadRequestForInvalidInput() throws Exception {
        mockMvc.perform(post(memberPath())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email":"not-an-email","role":null}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status").value(400));
    }

    @Test
    void updateRoleBindsTheTargetUserAndRequestedRole() throws Exception {
        UUID targetUserId = UUID.randomUUID();
        when(projectMemberService.updateMemberRole(
                any(UUID.class), any(UUID.class), any(UUID.class), any(UUID.class), any()
        )).thenReturn(ProjectMemberResponseDto.builder()
                .projectId(projectId)
                .userId(targetUserId)
                .role(ProjectMemberRole.ADMIN)
                .build());

        mockMvc.perform(patch(memberPath() + "/" + targetUserId + "/role")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"role":"ADMIN"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value(targetUserId.toString()))
                .andExpect(jsonPath("$.role").value("ADMIN"));
    }

    @Test
    void removeMemberReturnsNoContent() throws Exception {
        UUID targetUserId = UUID.randomUUID();

        mockMvc.perform(delete(memberPath() + "/" + targetUserId))
                .andExpect(status().isNoContent());

        verify(projectMemberService).removeMember(
                organizationId,
                projectId,
                targetUserId,
                currentUserId
        );
    }

    @Test
    void authorizationFailuresUseTheApiErrorContract() throws Exception {
        when(projectMemberService.listMembers(organizationId, projectId, currentUserId))
                .thenThrow(new UnauthorizedException("You are not a member of this project"));

        mockMvc.perform(get(memberPath()))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.status").value(401))
                .andExpect(jsonPath("$.message").value("You are not a member of this project"))
                .andExpect(jsonPath("$.path").value(memberPath()));
    }

    private String memberPath() {
        return "/api/v1/organizations/" + organizationId + "/projects/" + projectId + "/members";
    }
}
