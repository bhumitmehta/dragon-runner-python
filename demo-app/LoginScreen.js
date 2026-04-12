import React from 'react';
import { View, Text, TextInput, TouchableOpacity } from 'react-native';

const LoginScreen = ({
  isLoggedIn,
  username,
  password,
  setUsername,
  setPassword,
  handleLogin,
  setIsLoggedIn,
  styles,
  bugMode,
  setCurrentScreen
}) => (
  <View style={styles.screen}>
    <Text style={styles.title} accessibilityLabel="login-title">
      {isLoggedIn ? 'Profile' : 'Login'}
    </Text>
    {isLoggedIn ? (
      <View>
        <Text style={styles.welcomeText} accessibilityLabel="welcome-message">
          Welcome, {username}!
        </Text>
        <TouchableOpacity
          style={styles.logoutButton}
          onPress={() => {
            setIsLoggedIn(false);
            setUsername('');
            setPassword('');
          }}
          accessibilityLabel="logout-button"
        >
          <Text style={styles.buttonText}>Logout</Text>
        </TouchableOpacity>
      </View>
    ) : (
      <View>
        <TextInput
          style={styles.input}
          placeholder="Username"
          value={username}
          onChangeText={setUsername}
          accessibilityLabel="username-input"
          autoCapitalize="none"
        />
        <TextInput
          style={styles.input}
          placeholder="Password"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          accessibilityLabel="password-input"
        />
        {bugMode && (
          <Text style={styles.hintText} accessibilityLabel="login-hint">
            Hint: Any username works! (BUG)
          </Text>
        )}
        <TouchableOpacity
          style={styles.loginButton}
          onPress={handleLogin}
          accessibilityLabel="login-button"
        >
          <Text style={styles.buttonText}>Login</Text>
        </TouchableOpacity>
        <Text style={styles.credText}>Demo: demo / password123</Text>
      </View>
    )}
    <TouchableOpacity
      style={styles.backButton}
      onPress={() => setCurrentScreen('home')}
      accessibilityLabel="back-to-home"
    >
      <Text style={styles.backButtonText}>← Back</Text>
    </TouchableOpacity>
  </View>
);

export default LoginScreen;
