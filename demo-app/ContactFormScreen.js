import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, Alert } from 'react-native';

const ContactFormScreen = ({ validateEmail, styles, bugMode, setCurrentScreen }) => {
  const [formEmail, setFormEmail] = useState('');
  const [formMessage, setFormMessage] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = () => {
    if (bugMode) {
      setSubmitted(true);
      Alert.alert('Sent', 'Message sent!');
    } else {
      if (!validateEmail(formEmail)) {
        Alert.alert('Error', 'Please enter a valid email');
        return;
      }
      if (formMessage.length < 10) {
        Alert.alert('Error', 'Message must be at least 10 characters');
        return;
      }
      setSubmitted(true);
      Alert.alert('Success', 'Message sent successfully!');
    }
  };

  return (
    <View style={styles.screen}>
      <Text style={styles.title} accessibilityLabel="form-title">Contact Us</Text>
      <TextInput
        style={styles.input}
        placeholder="Your Email"
        value={formEmail}
        onChangeText={setFormEmail}
        accessibilityLabel="form-email-input"
        autoCapitalize="none"
      />
      <TextInput
        style={styles.input}
        placeholder="Message"
        value={formMessage}
        onChangeText={setFormMessage}
        accessibilityLabel="form-message-input"
        multiline
      />
      <TouchableOpacity
        style={styles.loginButton}
        onPress={handleSubmit}
        accessibilityLabel="submit-form"
      >
        <Text style={styles.buttonText}>Send</Text>
      </TouchableOpacity>
      {submitted && (
        <Text style={styles.successText} accessibilityLabel="form-success">
          Thank you for contacting us!
        </Text>
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
};

export default ContactFormScreen;
