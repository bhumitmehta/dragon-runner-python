import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity } from 'react-native';
import styles from './calculatorStyles';

const CalculatorScreen = ({ setCurrentScreen }) => {
  const [num1, setNum1] = useState('');
  const [num2, setNum2] = useState('');
  const [result, setResult] = useState(null);

  const calculate = (op) => {
    const a = parseFloat(num1) || 0;
    const b = parseFloat(num2) || 0;
    let res;
    switch (op) {
      case '+':
        res = a + b;
        break;
      case '-':
        res = a - b;
        break;
      case '*':
        res = a * b;
        break;
      case '/':
        res = b !== 0 ? a / b : 'Error';
        break;
      default:
        res = 0;
    }
    setResult(res);
  };

  return (
    <View style={styles.screen}>
      <Text style={styles.title} accessibilityLabel="calculator-title">Calculator</Text>
      <TextInput
        style={styles.input}
        placeholder="First number"
        keyboardType="numeric"
        value={num1}
        onChangeText={setNum1}
        accessibilityLabel="calc-input-1"
      />
      <TextInput
        style={styles.input}
        placeholder="Second number"
        keyboardType="numeric"
        value={num2}
        onChangeText={setNum2}
        accessibilityLabel="calc-input-2"
      />
      <View style={styles.calcButtons}>
        {['+', '-', '*', '/'].map((op) => (
          <TouchableOpacity
            key={op}
            style={styles.calcButton}
            onPress={() => calculate(op)}
            accessibilityLabel={`calc-${op === '*' ? 'multiply' : op === '/' ? 'divide' : op === '+' ? 'add' : 'subtract'}`}
          >
            <Text style={styles.calcButtonText}>{op}</Text>
          </TouchableOpacity>
        ))}
      </View>
      {result !== null && (
        <Text style={styles.resultText} accessibilityLabel="calc-result">
          Result: {result}
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

export default CalculatorScreen;
