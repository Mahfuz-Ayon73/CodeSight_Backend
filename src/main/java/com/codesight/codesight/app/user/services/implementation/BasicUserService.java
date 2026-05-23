package com.codesight.codesight.app.user.services.implementation;

import com.codesight.codesight.app.user.dto.UserResponseDto;
import com.codesight.codesight.app.user.model.UserModel;
import com.codesight.codesight.app.user.repository.UserRepository;
import com.codesight.codesight.app.user.services.UserService;
import com.codesight.codesight.common.exception.ResourceNotFoundException;
import com.codesight.codesight.common.utils.ObjectToDTOMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
@RequiredArgsConstructor
public class BasicUserService implements UserService {

    private final UserRepository userRepository;

    @Override
    public UserModel findById(UUID id) {
        return userRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("User not found with ID: " + id));
    }

    @Override
    public UserModel findByEmail(String email) {
        return userRepository.findByEmail(email)
                .orElseThrow(() -> new ResourceNotFoundException("User not found with Email: " + email));
    }

    @Override
    public UserModel save(UserModel user) {
        return userRepository.save(user);
    }

    @Override
    public UserResponseDto getUserProfile(UUID id) {
        UserModel user = findById(id);
        return ObjectToDTOMapper.toUserResponseDto(user);
    }
}
